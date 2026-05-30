from __future__ import annotations

def register_tools_endpoints(kernel):
    tool = kernel.lifecycle.get("tool")
    def tools_list():
        if tool is None: return {"tools": []}
        tools = tool.list_tools()
        result = [{"name": n, "description": i.get("description",""), "inputSchema": i.get("parameters",{"type":"object","properties":{}})} for n,i in tools.items()]
        return {"tools": result}
    def tools_call(name: str, arguments: dict = None):
        if tool is None: return {"content":[{"type":"text","text":"error: no tool plugin"}],"isError":True}
        r = tool.call(name, **(arguments or {}))
        return {"content":[{"type":"text","text":str(r)}]}
    return {"tools/list": tools_list, "tools/call": tools_call}

def register_resource_endpoints(kernel):
    kp = kernel.lifecycle.get("knowledge")
    def resources_list():
        resources = []
        if kp and kp._graph:
            for eid, e in kp._graph._entities.items():
                resources.append({"uri": f"knowledge://{eid}", "name": e.name, "description": f"{e.type}: {e.name}"})
        return {"resources": resources}
    def resources_read(uri: str):
        if uri.startswith("knowledge://") and kp:
            r = kp.query(uri.replace("knowledge://",""))
            return {"contents":[{"uri":uri,"text":str(r)}]}
        return {"contents":[]}
    return {"resources/list": resources_list, "resources/read": resources_read}

def register_prompt_endpoints(kernel):
    idp = kernel.lifecycle.get("identity")
    def prompts_list():
        return {"prompts":[{"name":"agent_identity","description":"获取 Agent 的身份上下文"}]}
    def prompts_get(name: str, arguments: dict = None):
        if name == "agent_identity" and idp:
            base = arguments.get("base_prompt","") if arguments else ""
            enriched = idp.enrich_prompt(base)
            return {"messages":[{"role":"system","content":{"type":"text","text":enriched}}]}
        return {"messages":[]}
    return {"prompts/list": prompts_list, "prompts/get": prompts_get}
