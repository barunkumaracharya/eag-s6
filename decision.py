from schemas import Goal, MemoryItem, DecisionOutput, ToolCall, HistoryItem
from llm_gatewayV3.client import LLM
from mcp.types import Tool
import json
import time
import re

def next_step(
    goal: Goal,
    hits: list[MemoryItem],
    attached: list[tuple[int, bytes]],
    history: list[HistoryItem],
    mcp_tools: list[Tool],
    run_id: str | None = None,
) -> DecisionOutput:
    print(f"    [Decision] next_step() called for Goal ID {goal.id}: {goal.text!r}")
    print(f"    [Decision] Hits count: {len(hits)}, Attached count: {len(attached)}, Available tools: {[t.name for t in mcp_tools]}")
    decider = LLM()

    # Format hits
    hits_formatted = ""
    if hits:
        temp_formatted = ""
        mem_idx = 1
        for hit in hits:
            if run_id is not None and hit.run_id == run_id and hit.kind != "fact":
                continue
            temp_formatted += f"Memory #{hit.id}:\n"
            temp_formatted += f"  - Goal {hit.goal_id} Output\n"
            temp_formatted += f"  - Kind: {hit.kind}\n"
            temp_formatted += f"  - Artifact ID: {hit.artifact_id}\n"
            val = hit.value
            contents_to_print = val
            if isinstance(val, dict):
                if val.get("tool") == "create_file" and isinstance(val.get("arguments"), dict) and "content" in val["arguments"]:
                    contents_to_print = val["arguments"]["content"]
                elif val.get("tool") == "read_file" and "result" in val:
                    res = val["result"]
                    if isinstance(res, str):
                        try:
                            res_dict = json.loads(res)
                            if isinstance(res_dict, dict) and "content" in res_dict:
                                contents_to_print = res_dict["content"]
                        except Exception:
                            pass
                    elif isinstance(res, dict) and "content" in res:
                        contents_to_print = res["content"]
                elif "extracted_facts" in val:
                    contents_to_print = val["extracted_facts"]
                elif "content" in val:
                    contents_to_print = val["content"]
                elif "result" in val:
                    contents_to_print = val["result"]
                elif "text" in val:
                    contents_to_print = val["text"]
            temp_formatted += f"  - Contents: {contents_to_print}\n"
            mem_idx += 1
        if temp_formatted:
            hits_formatted = temp_formatted

    # Format Goal Outputs from memory hits that belong to this run
    goal_outputs = ""
    if hits:
        temp_goals = ""
        for hit in hits:
            if run_id is not None and hit.run_id == run_id and hit.kind != "fact":
                temp_goals += f"Goal {hit.goal_id} :\n"
                val = hit.value
                contents_to_print = val
                if isinstance(val, dict):
                    if val.get("tool") == "create_file" and isinstance(val.get("arguments"), dict) and "content" in val["arguments"]:
                        contents_to_print = val["arguments"]["content"]
                    elif val.get("tool") == "read_file" and "result" in val:
                        res = val["result"]
                        if isinstance(res, str):
                            try:
                                res_dict = json.loads(res)
                                if isinstance(res_dict, dict) and "content" in res_dict:
                                    contents_to_print = res_dict["content"]
                            except Exception:
                                pass
                        elif isinstance(res, dict) and "content" in res:
                            contents_to_print = res["content"]
                    elif "extracted_facts" in val:
                        contents_to_print = val["extracted_facts"]
                    elif "content" in val:
                        contents_to_print = val["content"]
                    elif "result" in val:
                        contents_to_print = val["result"]
                    elif "text" in val:
                        contents_to_print = val["text"]
                temp_goals += f"  - Output: {contents_to_print}\n"
                if hit.artifact_id:
                    temp_goals += f"  - Artifact ID: {hit.artifact_id}\n"
        if temp_goals:
            goal_outputs = temp_goals
        else:
            goal_outputs = "No previous goal outputs."

    # Format attached artifacts
    attached_formatted = ""
    if attached:
        attached_formatted = "\n\n"
        for i, (art_id, content_bytes) in enumerate(attached, 1):
            try:
                content_str = content_bytes.decode("utf-8", errors="ignore")
            except Exception:
                content_str = "<binary data>"
            attached_formatted += f"Artifact #{i}:\n"
            attached_formatted += f"  - ID: {art_id}\n"
            attached_formatted += f"  - Content: {content_str}\n"

    # Format history (only for this goal or where artifact matches attached)
    history_formatted = ""
    attached_ids = {art_id for art_id, _ in attached}
    goal_history = [
        item for item in history 
        if item.goal_id == goal.id or (item.artifact_id is not None and item.artifact_id in attached_ids)
    ]
    print(f"    [Decision] Filtered history items for Goal {goal.id} (attached artifacts {attached_ids}): {len(goal_history)}")
    if goal_history:
        history_formatted = "\nACTIONS ALREADY PERFORMED FOR THIS GOAL:\n"
        for item in goal_history:
            if item.kind == "action":
                tool_name = item.tool
                
                # Retrieve tool description from mcp_tools
                tool_desc = ""
                for tool in mcp_tools:
                    curr_name = tool.name if hasattr(tool, "name") else tool.get("name")
                    if curr_name == tool_name:
                        tool_desc = tool.description if hasattr(tool, "description") else tool.get("description", "")
                        break
                        
                history_formatted += (
                    f"Iteration {item.iter}: Action taken:\n"
                    f"  - Goal ID: {item.goal_id}\n"
                    f"  - Tool Called: {tool_name}\n"
                    f"  - With Arguments: {item.arguments}\n"
                    f"  - Tool Details: {tool_desc}\n"
                    f"  - Output Result Summary: {item.result_descriptor}\n"
                    f"  - Output Artifact ID: {item.artifact_id}\n"
                )
            elif item.kind == "answer":
                history_formatted += (
                    f"Iteration {item.iter}: Intermediate Conclusion:\n"
                    f"  - Goal ID: {item.goal_id}\n"
                    f"  - Text: {item.text}\n"
                )

    # Format tools safely to dicts matching ToolDef for the Gateway
    tools_formatted = []
    for tool in mcp_tools:
        tool_dict = tool.model_dump() if hasattr(tool, "model_dump") else tool.dict()
        # The LLM Gateway expects 'input_schema' (snake_case). MCP Tool uses 'inputSchema'.
        input_schema = tool_dict.get("inputSchema") or tool_dict.get("input_schema") or {}
        tools_formatted.append({
            "name": tool_dict["name"],
            "description": tool_dict.get("description", ""),
            "input_schema": input_schema
        })

    system = (
        f"You are a decision manager. Your responsibility is to solve ONLY the specified Goal.\n\n"
        f" GUIDELINES FOR SOLVING THE GOAL ASSIGNED TO YOU:\n"
        f"- Analyze the target goal, facts, attached artifacts, and history to determine the next action.\n"
        f"- IMPORTANT: If the data to solve the goal is present in the artifact contents, you already have all required data, so you must extract the info and provide an 'answer'.\n"
        f"- Do NOT ask any questions. You must try to solve the goal without asking any user-related questions. If you need/want some data to solve the goal, search for a tool that does that and populate the 'tool_call' field (under tool_call) accordingly. If no tools can help or if you have all required data, provide an 'answer'.\n"
        f"- Do NOT provide an answer without a supporting fact behind it. The supporting fact must have arrived either from the memory hits, the goal history analysis, or previous tool calls.\n"
        f"- In the Memory Hits section, first go through the 'contents' of the memory item. If you get the desired information "
        f"from the 'contents' of the memory item, then DONOT MAKE ANY TOOL CALL FOR READING IT"
        f"- If the Goal is fully solved, that is, you can confidently provide an answer for it "
        f" by having proofs and reasoning based on attached historical actions and artifact details, then provide the final answer by populating the 'answer' field.\n"
        f"- If the Goal is not yet solved, perform a single step by calling one of the available tools. Populate the 'tool_call' field with the tool's name and arguments.\n"
        f"- When populating 'tool_call', the 'arguments' object MUST contain the specific arguments/parameters required by that tool as defined in the 'Available Tools' list. For example, if calling 'fetch_url', you must include the 'url' parameter (e.g. `\"arguments\": {{\"url\": \"https://en.wikipedia.org/wiki/Claude_Shannon\"}}`). Do not output empty arguments.\n"
        f"- Exactly one of 'answer' or 'tool_call' must be populated. The other must be null.\n"
        f"- YOU MUST ONLY USE TOOLS FROM THE PROVIDED LIST AND THE ARTIFACT CONTENTS TO SOLVE THE GOAL. "
        f"- YOU MUST NOT USE ANY WEB SEARCH OR FETCH URL TOOLS HERE UNLESS THE GOAL DESCRIPTION ITSELF TELLS YOU TO."
        f"- Before calling any tool, go through the ARTIFACT CONTENTS section, MEMORY HITS section, and GOAL HISTORY and check whether the tool call is necessary or not\n"
        f"- AS MUCH AS POSSIBLE, YOU SHOULD TRY TO NOT USE ANY TOOL. TRY TO SOLVE THE GOAL USING THE INFORMATION IN THE PROMPT ITSELF. USING TOOL SHOULD BE THE VERY LAST RESORT LITERALLY."
        f"- If you are using the create File tool, then make sure that the file name that you propose should be like a header which will give a hint about the contents within it."
        f"YOU MUST FIRST GO THROUGH EACH LINE AND ANALYZE THE ARTIFACT CONTENTS AND TRY TO SOLVE THE GOAL ONLY USING THE ARTIFACT CONTENTS AND NOTHING ELSE. "
        f"IF YOU ARE NOT SUCCEEDING IN SOLVING THE GOAL USING ONLY THE ARTIFACT CONTENTS, THEN YOU CAN USE A TOOL. "
        f"All the artifacts and their contents will be sent you as text in the user prompt. You donot need to call a file reader to read artifacts specifically. "
        f"- PRECEDENCE OF APPROACHES TO SOLVE THE GOAL IS AS FOLLOWS:\n"
        f"  1. Read each line of the MEMORY HITS SECTION, if the 'contents' of any of the memory item(s) have the"
        f" required / desired information, then provide the final answer for that goal by populating the 'answer' field.\n"
        f"  2. Read each line in ARTIFACT CONTENTS SECTIONS, MEMORY HITS, HISTORY and try to solve the goal only using that.\n"
        f"  3. Read each line in ARTIFACT CONTENTS SECTIONS, MEMORY HITS, HISTORY use the necessary data from the section and then call a tool to solve the goal.\n"
        f"  4. Analyze the goal and search for a tool that can solve it.\n"
        f"-All the artifacts and their contents will be sent you as text in the user prompt. You donot need to call a file reader to read artifacts specifically. "
        f"-While going through MEMORY HITS section, first go through the 'contents' of the memory item. If you get the desired information "
        f"from the 'contents' of the memory item, then DONOT MAKE ANY TOOL CALL FOR READING IT BECAUSE ITS A WASTE OF ITERATION\n\n"
        f"-THE TOOL YOU CALL MUST BE PRESENT IN THE PROVIDED TOOL LIST.\n"
        f"- IF YOU ARE USING A TOOL, ENSURE THAT THE TOOL DESCRIPTION MATCHES WITH WHAT YOU INTEND TO ACHEIVE BY USING THE TOOL\n"
        f"- FOR CALENDAR REMINDERS, USE CREATE FILE TOOL TO EMULATE CREATING REMINDERS IN A CALENDAR"
        f"- DONOT MAKE THE SAME TOOL CALL (WITH SAME ARGUMENTS) TWICE. IT SHOULD BE AT MOST ONCE"
        f"- DONOT SPEND MORE THAN 3 ITERATIONS FOR THE SAME GOAL. Look at the history of executed actions section for the goal. If 3 iterations have already been executed for the same GOAL ID,"
        f" then, in this iteration, DONOT MAKE ANY TOOL CALL. JUST POPULATE the 'answer' field and populate the answer with the contents present in the USER PROMPT."
        f"- Format the output strictly as a JSON object adhering to the DecisionOutput schema:\n"
        f"{json.dumps(DecisionOutput.model_json_schema())}"
    )

    # match = re.search(r'\bfrom', goal.text, flags=re.IGNORECASE)
    # cleaned_text = goal.text[:match.start()] + "from above text" if match else goal.text

    prompt = (
        f"TARGET GOAL FOR YOU TO SOLVE:\n"
        f"  - ID: {goal.id}\n"
        f"  - Description: {goal.text}\n"
        f"{history_formatted}\n"
        f"------ PREVIOUS GOAL OUTPUTS ------\n"
        f"{goal_outputs}\n"
        f"------ MEMORY HITS------\n"
        f"{hits_formatted}\n"
        f"------ ARTIFACT CONTENTS------\n"
        f"{attached_formatted}\n"
        f"------------------------------- END OF ARTIFACT CONTENTS------"
        f"YOU MUST FIRST GO THROUGH EACH LINE FIRST IN THE PREVIOUS GOAL OUTPUTS, THEN IN THE MEMORY HITS, THEN IN THE ARTIFACT CONTENTS AND TRY TO SOLVE THE GOAL ONLY USING THOSE AND NOTHING ELSE. "
        f"IF YOU ARE NOT SUCCEEDING IN SOLVING THE GOAL USING ONLY THE PREVIOUS GOAL OUTPUTS, MEMORY HITS AND ARTIFACT CONTENTS, THEN YOU CAN USE A TOOL, IF THERE IS AN UTMOST NEED TO USE IT. "
        f"BEFORE MAKING A TOOL CALL, SEE IN THE HISTORY IF THIS ACTION HAS ALREADY BEEN PERFORMED FOR THE GOAL."
        f"YOU MUST NOT USE ANY WEB SEARCH OR FETCH URL TOOLS HERE UNLESS THE GOAL DESCRIPTION ITSELF TELLS YOU TO."
    )

    retries = 0
    while True:
        try:
            print("    [Decision] Calling decider LLM (auto_route='decision')...")
            
            chat_kwargs = {
                "auto_route": "decision",
                "tools": tools_formatted,
                "response_format": {"type": "json_schema", "schema": DecisionOutput.model_json_schema()}
            }
            
            # If combined prompt is huge, bypass the gateway's router-tier limit (8K) by forcing Gemini
            combined_text = prompt + "\n" + system
            estimated_tokens = len(combined_text.split()) * 1.4
            if estimated_tokens > 8000:
                print(f"    [Decision] Combined prompt is large (~{estimated_tokens:.0f} tokens). Forcing Gemini provider ('g') to bypass router limit.")
                chat_kwargs["provider"] = "g"
                
            resp = decider.chat(
                prompt=prompt,
                system=system,
                cache_system=True,
                **chat_kwargs
            )
            print(f"    [Decision] LLM Response: {resp.get('text', '')}")
            
            # If the model natively called a tool, map it to DecisionOutput
            if resp.get("tool_calls"):
                first_call = resp["tool_calls"][0]
                decision_out = DecisionOutput(
                    answer=None,
                    tool_call=ToolCall(
                        name=first_call["name"],
                        arguments=first_call["arguments"]
                    ),
                )
            elif resp.get("parsed"):
                decision_out = DecisionOutput.model_validate(resp["parsed"])
            else:
                decision_out = DecisionOutput.model_validate_json(resp["text"])
                
            print(f"    [Decision] Parsed outcome: is_answer={decision_out.is_answer}, tool_call={decision_out.tool_call}")
            return decision_out
        except Exception as e:
            print(f"    [Decision] Error during LLM call or validation: {e}")
            if retries < 8:
                retries += 1
                print(f"    [Decision] Retrying in 10 seconds (attempt {retries}/8)...")
                time.sleep(10)
            else:
                raise e