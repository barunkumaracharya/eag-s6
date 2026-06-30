from mcp import ClientSession
from schemas import ToolCall
from artifacts import ArtifactStore

ARTIFACT_THRESHOLD_BYTES = 4096

async def execute(
    session: ClientSession,
    tool_call: ToolCall,
) -> tuple[str, str | None]:
    print(f"      [Action] execute() called for tool: {tool_call.name}")
    print(f"      [Action] Arguments: {tool_call.arguments}")
    
    # Call the tool using the MCP session
    result = await session.call_tool(tool_call.name, arguments=tool_call.arguments)
    
    # Extract the text payload from the result
    payload = (
        result.content[0].text
        if result.content and hasattr(result.content[0], "text")
        else str(result)
    )
    
    payload_bytes = payload.encode("utf-8")
    payload_size = len(payload_bytes)
    print(f"      [Action] Tool returned payload of size: {payload_size} bytes")
    
    if payload_size > ARTIFACT_THRESHOLD_BYTES:
        print(f"      [Action] Payload size exceeds threshold ({ARTIFACT_THRESHOLD_BYTES} bytes). Storing in ArtifactStore...")
        # Save content to ArtifactStore and get the numeric ID
        art_id = ArtifactStore.put(payload_bytes)
        print(f"      [Action] Stored artifact successfully. ID assigned: {art_id}")
        # Return first 500 characters and the stringified artifact ID
        return "First 500 characters of the content: " + payload[:500], str(art_id)
    else:
        print(f"      [Action] Payload size within threshold. Returning response directly.")
        # Return the entire payload and None as empty artifact ID
        return payload, None