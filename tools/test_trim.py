from core import Agent, MAX_CONTEXT_MESSAGES
class Fake: pass
f = Fake()
msgs = [{"role":"system","content":"sys"}]
for i in range(MAX_CONTEXT_MESSAGES+5):
    msgs.append({"role":"user","content":f"u{i}"})
# assistant placed early -> should be outside last window
msgs.insert(1, {"role":"assistant","content":"calling tool","tool_calls":[{"id":"call-1","name":"run_python","arguments":{"code":"print(1)"}}]})
# add tool result at the end
msgs.append({"role":"tool","tool_call_id":"call-1","name":"run_python","content":"ok"})
f.messages = msgs
normalized = Agent._trim_messages(f)
print('normalized count:', len(normalized))
for m in normalized:
    print(m)
