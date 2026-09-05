"""Production entrypoint for the disabled-by-default operator-control plugin."""
from __future__ import annotations

import importlib.util
import json
import os
import secrets
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, cast

__version__ = "1.1.0"


def _load(name: str, path: Path):
    spec=importlib.util.spec_from_file_location(name,path)
    if not spec or not spec.loader: raise RuntimeError(f"cannot load {path}")
    module=importlib.util.module_from_spec(spec); sys.modules[name]=module; spec.loader.exec_module(module); return module


@dataclass
class Runtime:
    enabled: bool
    controller: object | None = None
    broker: object | None = None
    adapters: dict[str, object] | None = None
    error: str | None = None


def _settings(ctx: object) -> Mapping[str, Any]:
    config=getattr(ctx,"config",{}) or {}
    plugins=config.get("plugins",{}) if isinstance(config,Mapping) else {}
    entries=plugins.get("entries",{}) if isinstance(plugins,Mapping) else {}
    value=entries.get("operator-control",{}) if isinstance(entries,Mapping) else {}
    return value if isinstance(value,Mapping) else {}


def configure(ctx: object, *, environ: Mapping[str,str] | None=None) -> Runtime:
    env=dict(os.environ if environ is None else environ); cfg=_settings(ctx)
    if cfg.get("managed_enabled") is not True: return Runtime(False,error="operator-control disabled or unconfigured")
    required=("board","kanban_db","policy_root","signing_key_file","supported_routes","managed_adapters")
    if any(not cfg.get(k) for k in required): return Runtime(False,error="managed configuration incomplete")
    home=Path(env.get("HERMES_HOME",Path.home()/".hermes")).resolve()
    root=Path(__file__).resolve().parents[2]
    managed=_load("operator_control_managed",Path(__file__).with_name("managed.py"))
    _load("operator_control_schemas",Path(__file__).with_name("schemas.py")); _load("operator_control_policy",Path(__file__).with_name("policy.py"))
    _load("operator_control_store",root/"tools/operator-control/store.py")
    broker_module=_load("operator_control_broker",root/"tools/operator-control/broker.py")
    control=home/"operator-control"; control.mkdir(parents=True,exist_ok=True,mode=0o700)
    reader=managed.NativeKanbanReader(Path(str(cfg["kanban_db"])),board=str(cfg["board"]))
    ledger=managed.SQLiteBudgetLedger(control/"managed-budget.db"); leases=managed.SQLiteLeaseRegistry(control/"managed-leases.db")
    # Acceptance retrieval is broker-owned durable state. No downstream task metadata is consulted.
    acceptance_path=control/"acceptances.json"
    def read_acceptance(task_id: str):
        try: data=json.loads(acceptance_path.read_text())
        except (OSError,json.JSONDecodeError): return None
        return data.get(task_id) if isinstance(data,dict) else None
    signing_key=Path(str(cfg["signing_key_file"])).read_bytes()
    signer=managed.AcceptanceSigner(signing_key)
    registry=managed.protected_local_adapter_registry(control/"local-provider.db")
    controller=managed.ManagedController(reader,acceptance_reader=read_acceptance,acceptance_verifier=signer.verify,
                                         leases=leases,budget_ledger=ledger,adapter_registry=registry)
    adapters={}
    for name in cfg["managed_adapters"]:
        if name != "local-sqlite": return Runtime(False,error=f"unreviewed managed adapter blocked: {name}")
        adapters[name]=registry.adapter(name)
    if not adapters: return Runtime(False,error="no reviewed managed adapter configured")
    broker=broker_module.ActionBroker(control/"broker.db",policy_root=Path(str(cfg["policy_root"])),supported_routes=set(cfg["supported_routes"]),signing_key=signing_key,managed_mode=True,managed_controller=controller)
    return Runtime(True,controller,broker,adapters)


def register(ctx):
    runtime=configure(ctx)
    schema={"name":"operator_control_execute","description":"Execute an approved protected action; fails closed unless managed mode and a reviewed adapter are configured.","parameters":{"type":"object","properties":{"approval_id":{"type":"string"},"adapter":{"type":"string"},"intent":{"type":"object"}},"required":["approval_id","adapter","intent"]}}
    def execute(params,**_kwargs):
        if not runtime.enabled or runtime.broker is None: return json.dumps({"success":False,"error":runtime.error or "operator-control disabled"})
        adapter=(runtime.adapters or {}).get(params.get("adapter"))
        if adapter is None: return json.dumps({"success":False,"error":"managed adapter unavailable"})
        try: return json.dumps({"success":True,"result":cast(Any,runtime.broker).execute(params["intent"],params["approval_id"],adapter)})
        except Exception as exc: return json.dumps({"success":False,"error":str(exc)})
    ctx.register_tool(name="operator_control_execute",toolset="operator_control",schema=schema,handler=execute)
    def pre_tool_call(tool_name,params,**_kwargs):
        if tool_name=="operator_control_execute" and not runtime.enabled: return {"allow":False,"reason":runtime.error}
        return None
    ctx.register_hook("pre_tool_call",pre_tool_call)
    return runtime
