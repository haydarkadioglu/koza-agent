import json
import uuid
import logging
from typing import Dict, Any, List

class FlowNode:
    def __init__(self, id: str, tool_name: str, params: Dict[str, Any], depends_on: List[str] = None):
        self.id = id
        self.tool_name = tool_name
        self.params = params
        self.depends_on = depends_on or []
        self.result = None
        self.status = "pending" # pending, running, success, failed

class FlowDAG:
    def __init__(self, name: str, nodes: List[FlowNode]):
        self.id = str(uuid.uuid4())
        self.name = name
        self.nodes = {n.id: n for n in nodes}
    
    def execute(self, handlers: Dict[str, Any]) -> Dict[str, Any]:
        """Execute the DAG."""
        completed = set()
        in_progress = set()
        failed = False
        
        while len(completed) + len(failed and [1] or []) < len(self.nodes):
            progress_made = False
            
            for node_id, node in self.nodes.items():
                if node.status != "pending":
                    continue
                
                # Check dependencies
                can_run = True
                for dep_id in node.depends_on:
                    if dep_id not in completed:
                        can_run = False
                        break
                
                if can_run:
                    progress_made = True
                    node.status = "running"
                    in_progress.add(node_id)
                    
                    try:
                        handler = handlers.get(node.tool_name)
                        if not handler:
                            raise ValueError(f"Tool {node.tool_name} not found in registry.")
                        
                        # Replace templates in params from previous results
                        resolved_params = self._resolve_params(node.params)
                        
                        # Call handler
                        result = handler(resolved_params)
                        node.result = result
                        node.status = "success"
                        completed.add(node_id)
                    except Exception as e:
                        node.result = str(e)
                        node.status = "failed"
                        failed = True
                        break # Stop execution on failure
                    
                    in_progress.remove(node_id)
            
            if failed or not progress_made:
                break
                
        return {
            "flow_id": self.id,
            "status": "failed" if failed else "success",
            "results": {n_id: n.result for n_id, n in self.nodes.items()}
        }

    def _resolve_params(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Resolve ${node_id.result} variables in params."""
        import copy
        resolved = copy.deepcopy(params)
        
        def _replace_in_str(s: str) -> str:
            if not isinstance(s, str): return s
            for node_id, node in self.nodes.items():
                if node.status == "success":
                    placeholder = f"${{{node_id}.result}}"
                    if placeholder in s:
                        s = s.replace(placeholder, str(node.result))
            return s
            
        def _walk(obj):
            if isinstance(obj, dict):
                return {k: _walk(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [_walk(v) for v in obj]
            elif isinstance(obj, str):
                return _replace_in_str(obj)
            return obj
            
        return _walk(resolved)

def handle_flow_execute(action: str, params: Dict[str, Any]) -> str:
    """Execute a workflow DAG."""
    try:
        from tools.registry import ALL_HANDLERS
        
        nodes_data = params.get("nodes", [])
        name = params.get("name", "Unnamed Flow")
        
        nodes = []
        for n in nodes_data:
            nodes.append(FlowNode(
                id=n.get("id"),
                tool_name=n.get("tool_name"),
                params=n.get("params", {}),
                depends_on=n.get("depends_on", [])
            ))
            
        dag = FlowDAG(name, nodes)
        result = dag.execute(ALL_HANDLERS)
        
        return json.dumps(result, indent=2)
    except Exception as e:
        return f"Error executing flow: {str(e)}"

TOOL_DEFINITIONS = [
    {
        "name": "flow_execute",
        "description": "Execute a DAG workflow of multiple tool calls.",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Name of the workflow"
                },
                "nodes": {
                    "type": "array",
                    "description": "List of nodes in the DAG.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string", "description": "Unique ID for this node."},
                            "tool_name": {"type": "string", "description": "The name of the tool to execute."},
                            "params": {"type": "object", "description": "Parameters to pass to the tool. Can use ${node_id.result} to refer to outputs of previous nodes."},
                            "depends_on": {"type": "array", "items": {"type": "string"}, "description": "List of node IDs that must finish before this one starts."}
                        },
                        "required": ["id", "tool_name", "params"]
                    }
                }
            },
            "required": ["nodes"]
        }
    }
]

def _flow_execute_handler(args: Dict[str, Any]) -> str:
    return handle_flow_execute("execute", args)

HANDLERS = {
    "flow_execute": _flow_execute_handler
}
