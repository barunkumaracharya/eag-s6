from schemas import Goal, MemoryItem, Observation, HistoryItem
from llm_gatewayV3.client import LLM
import json
import time

def observe(
    query: str,
    hits: list[MemoryItem],
    history: list[HistoryItem],
    prior_goals: list[Goal],
    run_id: str,
) -> Observation: 

    print(f"  [Perception] observe() called: prior_goals_count={len(prior_goals)}, history_len={len(history)}")
    supervisor = LLM()
    hits_formatted = ""
    if hits:
        hits_formatted = "\nRelevant Facts / Assumptions / Background :\n"
        for i, hit in enumerate(hits, 1):
            hits_formatted += f"Memory #{i}:\n"
            hits_formatted += f"  - Kind: {hit.kind}\n"
            hits_formatted += f"  - Descriptor: {hit.descriptor}\n"
            hits_formatted += f"  - Artifact ID: {hit.artifact_id}\n"
            hits_formatted += f"  - Contents: {hit.value}\n"
                
    if not history:
        print("  [Perception] No history yet. Generating initial goals list...")
        system = (
            f"You are a supervisor manager. Your task is to break down the user's high-level problem statement "
            f"into a list of small, structured, actionable goals that can be executed by weaker, smaller models. "
            f"Your responsibility is to act as a supervisor, review tasks, analyze, and decide the next course of action.\n"
            f"Guidelines:\n"
            f"- Each goal should be simple and focused.\n"
            f"- NEVER use reference-based words or relative pronouns (such as 'the page', 'that', 'this', 'it', 'the content', etc.) in the goal text, except when explicitly referencing the goal IDs of previous goals (e.g. 'using the output of Goal 1' or 'based on the artifact from Goal 2')." 
            f"Be precise and write the exact text, URL, goal ID, string, name, or value directly. For example, write 'Access the URL https://example.com/source_page' instead of 'Access the provided URL'.\n"
            f"- Never ask any further questions back to the user. If any information is missing, define it as a goal.\n"
            f"- Look at the descriptor and kind of the relevant memory items to see if they are relevant to any of the goals.\n"
            f"- If a memory item is relevant to a goal, populate its corresponding 'Artifact ID' in the 'attach_artifact_id' list field of that Goal in the output Goal list.\n"
            f"- The Goal ID should be an INTEGER and NOTHING ELSE.\n"
            f"- The Goal 'Text' field should describe what the goal is about. It should have an action item and the context behind that item. The goal should clearly define WHAT AND WHY.\n"
            f"- The Goal 'done' field should be false."
            f"- The Goal 'attach_artifact_id' field should be a list of integer IDs of the artifacts that are relevant to the goal. Use an empty list if there are no attached artifacts.\n"
            f"- The Goal 'iteration_number_of_completion' field should be empty. DONOT POPULATE IT."
            f"  DONOT invent, create artifact Ids that are not present. As part of verification, if you are populating" 
            f" attach_artifact_id, make sure the IDs are present in the artifact Ids shared to you as part of the prompt.\n"
            f"- If the user has asked for some information extraction or list like 'tell me 10 things', 'give some detail'"
            f", until and unless the goal outcome"
            f" doesnt contain list or points entailing them, DONOT consider it as done. In such cases, while describing the"
            f" goal, ensure that the goal description is such that weaker models can clearly identify that they have to give a list, points as answers.\n"
            f"- Design the goals and their description such that there is no overlap in the work done for them. Encourage re-use of results from previous goals.\n"
            f"- A single goal should end in a single line. If you see that you are using 'coordinating conjunction words' in a goal "
            f" definition, you can further decompose that goal into 2 goals. So, none of the goal definition should have any"
            f" conjuction words. If data from a goal is needed in another goal, then, just refer that goal Id in the goal defintion. "
            f" If in a particular goal, there is a need to refer / use an item from memory, then just mention 'MEMORY HITS'  in the goal description and not by any memory Id  or memory number. For ex - "
            f" Instead of 'Get Pythogoreas theorem using memory 9', you should write 'Get Pythogoreas theorem using MEMORY HITS'."
            f"- Memory Hits, Artifact Contents are something that will passed along with the goal description to the weaker models, but, they "
            f" wont have access to the original user query. So, you have to mention the exact task & details in the sub goal description based on the user query."
            f"- You can and should only use CONJUNCTION in a goal definition when the task is same, but the operands are many. For ex- Get me 1g of Gold and Silver. Do sum of 3 and 5. Give me multiplication tables of 12, 16 and 58"
            f"- Weaker Models are going to look at your goals and process it. Make sure that the goals definition"
            f" are such that the work done in goal 1 is not repeated in goal 2, when the goals are executed in sequential order.\n"
            f"- Ensure SEPARATION OF CONCERN while defining goals.\n"
            f"- Donot create any sub goals for DATE / TIME / TIMESTAMP / CALENDAR related calculations. Do those calculations yourself and use that information in creating the next goals\n"
            f"- Validate that the current goal does not overlap with previous goal. Read the entire goal text, understand its meaning, read the previous goal text, understand its meaning and compare both and make sure that the definitions are different. There is no overlap"
            f"- The end sub goal should always be a \"ANSWER\" type goal, where the goal should always be to summarize and answer based on results of previous goals and the questions / actions asked by the user.\n"
            f"- A goal should be marked as done, only when atleast one action is taken for that Goal ID. You must check each iteration"
            f" in the History of executed actions and verify if atleast one iteration is spent on that goal ID by matching the"
            f" Goal ID in the action history. This is a mandatory rule for a goal to be marked as done. Otherwise, DONOT mark the goal as done.\n"
            f"- Second rule for deciding if a goal is done is that you have to look at that goal's description."
            f"If there is an action in the history of actions executed that clearly indicates that the goal's objective has been achieved, only then"
            f" mark it as done, otherwise, you MUST NOT mark it done. That action must be a single item  and not a combination of different action items in history."
            f"- You dont have to solve the goal or see whether it is getting solved or not. Your job is only to go through each ITERATION in history "
            f" of actions executed and for each ITERATION in history, determine the semantic meaning of the action executed in that ITERATION and compare it with the SEMANTIC MEANING of the "
            f" the goal description of the Goal. If the semantic meaning matches, then, you can mark the goal as done, otherwise false."
            f" Remember, exactly ATLEAST ONE ACTION'S SEMANTIC MEANING must match or be a superset of the GOAL DESCRIPTION SEMANTIC MEANING for that goal to be marked as done. "
            f"- For each goal, if it has been successfully completed, set 'done' to true. If it still needs further processing or tool calls to be resolved, set 'done' to false.\n"
            f"- For each goal, if you are marking it as done, then in the 'iteration_number_of_completion' of the goal, note down the iteration number on the basis of which you marked it as done."
            f"- To validate, go through the actions performed in the iteration with 'iteration_number_of_completion' in History of executed actions and check whether  actions executed in that iteration are solving the goal's requirements. The 'Result Summary' of that iteration will help you understand what that iteration did."
            f"- By Adhering to the above rules, TRY TO CREATE AS LESS GOALS AS POSSIBLE."
            f"- Perform this step after you have created goals based on above rules. Create a TOPOLOGICALLY SORTED GRAPH of all the Goals that you have created based on the dependency list of the respective goal."
            f" You can determine all the goals, a goal is dependent on, by looking at the Goal IDs referenced in its desciption. Ex - Goal 7: Get data summarized from result of goal 1 and goal 5. In this case, Goal 7 is dependent on Goal 1 and Goal 5."  
            f" All the nodes that are disjoint and are only 1 node graphs, you must eliminate those goals from the final list as they are not being used by any other goals."
            f" For ex - Goal 1: Get data from page 1. Goal 2: Get data from page 2. Goal 3: See results of Goal 2 and summarize. In this case Goal 1 will be eliminated because its output is not being used by any other goal. "
            f" If i were to create a TOPOLOGICALLY SORTED GRAPH of all the goals above, then goal 2 and 3 will be part of one graph and goal 1 will be separate (1 node graph). Hence, we should eliminate goal 1 and the final list that we print should have goal 2 and 3."
            f" Only that, we will renumber the goal 2 and 3 as the new goal 1 and goal 2. So, final goal output -  Goal 1: Get data from page 2. Goal 2: See results of Goal 1 and summarize." 
            f"- Format the output strictly as a JSON object adhering to the Observation schema:\n"
            f"{json.dumps(Observation.model_json_schema())}"
        )
        prompt = (
            f"Problem Statement: {query}\n"
            f"Facts/Assumptions/Background:\n{hits_formatted}\n\n"
            f"History of Executed Actions and Results:\nEMPTY, NO ACTIONS PERFORMED YET"
        )
    else:
        print(f"  [Perception] Reviewing history of actions to evaluate goals status...")
        prior_goals_json = [g.model_dump() for g in prior_goals]
        history_formatted = ""
        for item in history:
            if item.kind == "action":
                history_formatted += (
                    f"Iteration {item.iter}: Action taken on Goal '{item.goal_id}':\n"
                    f"  - Tool: {item.tool}\n"
                    f"  - Arguments: {item.arguments}\n"
                    f"  - Result Summary: {item.result_descriptor}\n"
                    f"  - Generated Artifact ID: {item.artifact_id}\n"
                )
            elif item.kind == "answer":
                history_formatted += (
                    f"Iteration {item.iter}: Answer provided for Goal '{item.goal_id}':\n"
                    f"  - Text: {item.text}\n"
                )

        system = (
            f"You are a supervisor manager. Your responsibility is to act as a supervisor, review tasks, analyze, "
            f"and decide the next course of action. You must NEVER solve any goal yourself; your job is solely to "
            f"review the status of tasks, analyze, and decide the next course of action.\n\n"
            f"Your task is to review the assumptions, facts, background information, "
            f"prior list of goals, and the history of executed actions/results. Analyze the history of actions, "
            f"specifically looking at the 'Result Summary' and 'Generated Artifact ID' in the history. "
            f"Determine if the goals are completed based on their results, and output the updated list of goals.\n\n"
            f"Guidelines:\n"
            f"- Do not attempt to solve the goals. Your job is only to review the 'Result Summary' of each executed action to determine if the goal is finished or needs further processing.\n"
            f"- A goal should be marked as done, only when atleast one action is taken for that Goal ID. You must check each iteration"
            f" in the History of executed actions and verify if atleast one iteration is spent on that goal ID by matching the"
            f" Goal ID in the action history. This is a mandatory rule for a goal to be marked as done. Otherwise, DONOT mark the goal as done.\n"
            f"- Second rule for deciding if a goal is done is that you have to look at that goal's description."
            f"If ONLY the LAST action in the history of actions executed clearly indicates that the goal's objective has been achieved, only then"
            f" mark it as done, otherwise, you MUST NOT mark it done."
            f"- You dont have to solve the goal or see whether it is getting solved or not. Your job is only to go through each ITERATION in history "
            f" of actions executed and for each ITERATION in history, determine the semantic meaning of the action executed in that ITERATION and compare it with the SEMANTIC MEANING of the "
            f" the goal description of the Goal. If the semantic meaning matches, then, you can mark the goal as done, otherwise false."
            f" Remember, exactly LAST ACTION'S SEMANTIC MEANING must match or be a superset of the GOAL DESCRIPTION SEMANTIC MEANING for that goal to be marked as done. "
            f"- For each goal, if it has been successfully completed, set 'done' to true. If it still needs further processing or tool calls to be resolved, set 'done' to false.\n"
            f"- For each goal, if you are marking it as done, then in the 'iteration_number_of_completion' of the goal, note down the iteration number on the basis of which you marked it as done."
            f"- To validate, go through the last action performed for that goal ID in the iteration with 'iteration_number_of_completion' in History of executed actions and check whether the last action executed in that iteration is solving the goal's requirements. The 'Result Summary' of that iteration will help you understand what that iteration did."
            f"- If defining a new goal, NEVER use reference-based words or relative pronouns (such as 'provided URL', 'the page', 'that', 'this', 'it', 'the content', etc.) in the goal text, except when explicitly referencing the goal IDs of previous goals (e.g. 'using the output of Goal 1' or 'based on the artifact from Goal 2'). Be precise and write the exact text, URL, string, name, or value directly. For example, write 'Access the URL https://example.com/source_page' instead of 'Access the provided URL'.\n"
            f"- Carefully look at the 'Result Summary' and 'Generated Artifact ID' of actions in the history. If you find that a result/artifact from a previous step is relevant and required to finish the next unfinished goal, populate its 'Generated Artifact ID' in the 'attach_artifact_id' list field of the next unfinished goal.\n"
            f"- Remember, You should only add a 'Generated Artifact ID' of actions in history to the attach_artifact_id list of an unfinished goal, if and only if the goal ID mentioned in the action history for this 'Generated Artifact ID' is present in the goal description of the next unfinished goal, otherwise, you must not add it."
            f" Verify the above rules twice before giving your final output."
            f"- Never ask any further questions back to the user. If any information is missing, define it as a new goal in the goals list.\n"
            f"- Keep the original 'id' and 'text' for each of the existing goals.\n"
            f"- Design the goals and their description such that there is no overlap in the work done for them. Encourage re-use of results from previous goals.\n"
            f"- A single goal should end in a single line. If you see that you are using 'coordinating conjunction words' in a goal "
            f" definition, you can further decompose that goal into 2 goals. So, none of the goal definition should have any"
            f" conjuction words. If data from a goal is needed in another goal, then, just refer that goal Id in the goal definition. "
            f"- Weaker Models are going to look at your goals and process it. Make sure that the goals definition"
            f" are such that the work done in goal 1 is not repeated in goal 2, when the goals are executed in sequential order."
            f"- Ensure SEPARATION OF CONCERN while defining goals.\n"
            f"- The end sub goal should always be a \"ANSWER\" type goal, where the goal should always be to summarize and answer based on results of previous goals and the questions / actions asked by the user.\n"
            f"- Format the output strictly as a JSON object adhering to the Observation schema:\n"
            f"{json.dumps(Observation.model_json_schema())}"
        )
        prompt = (
            f"Facts/Assumptions/Background:\n{hits_formatted}\n\n"
            f"Prior Goals:\n{json.dumps(prior_goals_json, indent=2)}\n\n"
            f"History of Executed Actions and Results:\n{history_formatted}"
            f"\nCRITICAL INSTRUCTION: YOU MUST NOT ADD / CREATE A NEW GOAL WHICH IS NOT ALREADY DEFINED."
            f"- A goal should be marked as done, only when atleast one action is taken for that Goal ID. You must check each iteration"
            f" in the History of executed actions and verify if atleast one iteration is spent on that goal ID by matching the"
            f" Goal ID in the action history. This is a mandatory rule for a goal to be marked as done. Otherwise, DONOT mark the goal as done.\n"
            f"- Second rule for deciding if a goal is done is that you have to look at that goal's description."
            f"If there is an action in the history of actions executed that clearly indicates that the goal's objective has been achieved, only then"
            f" mark it as done, otherwise, you MUST NOT mark it done. That action must be a single item  and not a combination of different action items in history."
            f"- You dont have to solve the goal or see whether it is getting solved or not. Your job is only to go through each ITERATION in history "
            f" of actions executed and for each ITERATION in history, determine the semantic meaning of the action executed in that ITERATION and compare it with the SEMANTIC MEANING of the "
            f" the goal description of the Goal. If the semantic meaning matches, then, you can mark the goal as done, otherwise false."
            f" Remember, exactly ATLEAST ONE ACTION'S SEMANTIC MEANING must match or be a superset of the GOAL DESCRIPTION SEMANTIC MEANING for that goal to be marked as done. "
            f"- For each goal, if it has been successfully completed, set 'done' to true. If it still needs further processing or tool calls to be resolved, set 'done' to false.\n"
            f"- For each goal, if you are marking it as done, then in the 'iteration_number_of_completion' of the goal, note down the iteration number on the basis of which you marked it as done."
            f"- To validate, go through the actions performed in the iteration with 'iteration_number_of_completion' in History of executed actions and check whether  actions executed in that iteration are solving the goal's requirements. The 'Result Summary' of that iteration will help you understand what that iteration did."

        )

    retries = 0
    validation_feedback = ""
    while True:
        try:
            current_system = system
            if validation_feedback:
                current_system = (
                    f"{system}\n\n"
                    f"[LEARNING/WARNING: Your previous response failed validation with the following error:\n"
                    f"{validation_feedback}\n"
                    f"Please correct the response structure to strictly match the requested JSON schema.]"
                )

            print("  [Perception] Calling supervisor LLM (Gemini)...")
            resp = supervisor.chat(
                prompt,
                system=current_system,
                cache_system=False if validation_feedback else True,
                provider="g",
                response_format={"type": "json_schema", "schema": Observation.model_json_schema()}
            )
            print(f"  [Perception] LLM Response: {resp['text']}")
            observation = Observation.model_validate_json(
                resp["text"],
                context={"history_len": len(history)}
            )
            observation.all_done = all(g.done for g in observation.goals) if observation.goals else False
            print(f"  [Perception] Parsed observation: all_done={observation.all_done}, goals_count={len(observation.goals)}")
            return observation
        except Exception as e:
            print(f"  [Perception] Error during LLM call or validation: {e}")
            import pydantic
            if isinstance(e, (pydantic.ValidationError, json.JSONDecodeError, ValueError)):
                validation_feedback = str(e)
            if retries < 5:
                retries += 1
                print(f"  [Perception] Retrying in 5 seconds (attempt {retries}/5)...")
                time.sleep(5)
            else:
                raise e
