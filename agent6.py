import action
from mcp.types import Tool
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from contextlib import asynccontextmanager
import perception
import decision
import os
import uuid
import sys
from dotenv import load_dotenv
from schemas import Goal, MemoryItem, Observation, HistoryItem
import memory
from llm_gatewayV3.client import LLM, ask
import artifacts


MAX_ITERATIONS = 20
llm = LLM()

def final_answer_from(history: list[HistoryItem]) -> str:
    """Return the final answer from the last goal."""
    if not history:
        return ""
    
    last_goal_id = history[-1].goal_id
    goal_items = [item for item in history if item.goal_id == last_goal_id]
    
    # 1. see if there artifact_id for that history item is not none, then fetch that artifact_id and show its contents
    for item in reversed(goal_items):
        if item.artifact_id is not None:
            if artifacts.exists(item.artifact_id):
                return artifacts.get_bytes(item.artifact_id).decode("utf-8", errors="ignore")
                
    # 2. otherwise, if its a answer goal then return item.text
    for item in reversed(goal_items):
        if item.kind == "answer":
            return item.text or ""
            
    # 3. or if the goal_id is present in memory, then return the contents of that memory item
    if memory.MEMORY_FILE.exists():
        try:
            import json
            with open(memory.MEMORY_FILE, "r", encoding="utf-8") as f:
                mem_data = json.load(f)
                if isinstance(mem_data, list):
                    for mem_item in reversed(mem_data):
                        if mem_item.get("goal_id") == last_goal_id:
                            art_id = mem_item.get("artifact_id")
                            if art_id is not None:
                                if artifacts.exists(art_id):
                                    return artifacts.get_bytes(art_id).decode("utf-8", errors="ignore")
                            val = mem_item.get("value")
                            import re
                            from pathlib import Path
                            
                            def find_txt_files(obj) -> list[str]:
                                files = []
                                if isinstance(obj, str):
                                    for match in re.findall(r'[a-zA-Z0-9_\-\./\\]+\.txt', obj):
                                        files.append(match)
                                elif isinstance(obj, dict):
                                    for v in obj.values():
                                        files.extend(find_txt_files(v))
                                elif isinstance(obj, list):
                                    for v in obj:
                                        files.extend(find_txt_files(v))
                                return files
                                
                            txt_files = find_txt_files(val)
                            for txt_file in txt_files:
                                for base_dir in [Path("sandbox"), Path(".")]:
                                    resolved_path = (base_dir / txt_file).resolve()
                                    if resolved_path.exists() and resolved_path.is_file():
                                        try:
                                            return resolved_path.read_text(encoding="utf-8", errors="ignore")
                                        except Exception:
                                            pass
                                            
                            if isinstance(val, dict):
                                if "result" in val:
                                    return str(val["result"])
                                if "text" in val:
                                    return str(val["text"])
                            return str(val) if val is not None else ""
        except Exception:
            pass
            
    return ""

async def run(query: str) -> str:
    print(f"\n[Agent6] Starting run with query: {query!r}")
    ensure_gateway()
    run_id = uuid.uuid4().hex[:8]
    print(f"[Agent6] Generated run_id: {run_id}")
    history: list[HistoryItem] = []
    prior_goals: list[Goal] = []

    # Durable memory: classify the user's query so facts/preferences
    # in it survive into future runs.
    print(f"[Agent6] Recording query to memory...")
    memory.remember(query, source="user_query", run_id=run_id)

    async with mcp_session() as session:
        mcp_tools = await load_tools(session)
        tools = mcp_tools_for_decision(mcp_tools)

        for it in range(1, MAX_ITERATIONS + 1):
            print(f"\n--- [Agent6 Loop] Iteration {it} ---")
            hits = memory.read(query, history)
            print(f"[Agent6] Read {len(hits)} facts from memory: {[h.descriptor for h in hits]}")
            
            print(f"[Agent6] Calling perception.observe...")
            obs = perception.observe(query, hits, history, prior_goals, run_id)
            prior_goals = obs.goals
            print(f"[Agent6] Perception returned goals (all_done={obs.all_done}):")
            for g in obs.goals:
                print(f"  - Goal ID {g.id}: {g.text!r} (done={g.done}, attach_artifact_id={g.attach_artifact_id})")
                
            if obs.all_done:
                print(f"[Agent6] All goals marked done! Breaking loop.")
                break

            goal = obs.next_unfinished()
            print(f"[Agent6] Next unfinished goal to solve: ID {goal.id} - {goal.text!r}")
            attached = []
            if goal.attach_artifact_id:
                for art_id in goal.attach_artifact_id:
                    if artifacts.exists(art_id):
                        print(f"[Agent6] Goal has attached artifact ID: {art_id}. Fetching content...")
                        attached.append((
                            art_id,
                            artifacts.get_bytes(art_id),
                        ))

            print(f"[Agent6] Calling decision.next_step for goal ID {goal.id}...")
            decision_memory_hits = [h for h in hits if h.run_id == run_id or h.kind == "fact"]
            out = decision.next_step(goal, decision_memory_hits, attached, history, tools, run_id=run_id)
            print(f"[Agent6] Decision output: answer={out.answer!r}, tool_call={out.tool_call}")

            if out.is_answer:
                print(f"[Agent6] Step resulted in intermediate/final answer: {out.answer!r}")
                history.append(HistoryItem(
                    iter=it,
                    kind="answer",
                    goal_id=goal.id,
                    text=out.answer
                ))
                memory.record_outcome(
                    tool_call=None,
                    result_text=out.answer,
                    artifact_id=None,
                    run_id=run_id,
                    goal_id=goal.id,
                )
                continue

            print(f"[Agent6] Step resulted in tool call: {out.tool_call.name} with args {out.tool_call.arguments}")
            result_text, art_id = await action.execute(session, out.tool_call)
            print(f"[Agent6] Tool executed. Result text len: {len(result_text)}, generated artifact ID: {art_id}")
            
            print(f"[Agent6] Recording outcome to memory...")
            memory.record_outcome(
                tool_call=out.tool_call,
                result_text=result_text,
                artifact_id=art_id,
                run_id=run_id,
                goal_id=goal.id,
            )
            history.append(HistoryItem(
                iter=it,
                kind="action",
                goal_id=goal.id,
                tool=out.tool_call.name,
                arguments=out.tool_call.arguments,
                result_descriptor=result_text[:300],
                artifact_id=int(art_id) if art_id else None
            ))

    final_ans = final_answer_from(history)
    print(f"\n[Agent6] Run complete. Final Answer: {final_ans!r}")
    return final_ans

@asynccontextmanager
async def mcp_session():
    print("[Agent6] Starting stdio MCP session...")
    server_params = StdioServerParameters(
        command=sys.executable,
        args=["-u", "mcp_server.py"],
    )
    async with stdio_client(server_params) as (read, write):
        print("[Agent6] MCP stdio client connected. Creating session...")
        async with ClientSession(read, write) as session:
            print("[Agent6] Initializing MCP session...")
            await session.initialize()
            print("[Agent6] MCP session initialized successfully.")
            yield session

async def load_tools(session: ClientSession) -> list[Tool]:
    tools = (await session.list_tools()).tools
    print(f"Loaded {len(tools)} tools from MCP server")
    return tools

def mcp_tools_for_decision(mcp_tools: list[Tool]) -> list[Tool]:
    """
    Filter MCP tools into a list suitable for use by the decision engine.
    """
    return mcp_tools

def ensure_gateway():
    """Ensure the LLM gateway is running, with a fallback to a dummy provider."""
    try:
        import httpx
        httpx.get("http://localhost:8101/v1/status", timeout=2.0).raise_for_status()
    except Exception:
        # not running or broken; attempt restart, falling back to dummy if needed
        try:
            import subprocess
            subprocess.Popen(["uv", "run", "uvicorn", "llm_gatewayV3.main:app", "--host", "localhost", "--port", "8101"],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            # If uv or uvicorn not available, patch LLM to use a dummy provider
            def always_dummy(*args, **kwargs) -> dict:
                prompt = kwargs.get("prompt") or (args[0] if args else "")
                return {"text": f"[dummy response to: {prompt[:200]}]"}
            LLM.chat = always_dummy

if __name__ == "__main__":
    import asyncio
    import sys
    load_dotenv()
    
    query = sys.argv[1] if len(sys.argv) > 1 else """What credit card should I get? I have an annual income of around ₹10,00,000. I frequently travel, and I'd like to get good rewards on travel-related expenses. I also like dining out, so a card that gives good cashback or points on restaurants would be great. I usually use my card for most purchases, including groceries and shopping online. Please suggest a good credit card and tell me how to get it."""
    print(f"Running Agent with query: {query}")
    answer = asyncio.run(run(query))
    print("\n=== Agent's Final Answer ===")
    print(answer)