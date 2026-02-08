interface UserActionInput {
  videoId: string;
  host?: string | null;
  action: "like";
}

export async function sendUserAction(apiBase: string, input: UserActionInput): Promise<void> {
  const response = await fetch(new URL("/api/user-action", apiBase), {
    method: "POST",
    headers: {
      "content-type": "application/json"
    },
    body: JSON.stringify({
      video_id: input.videoId,
      host: input.host ?? null,
      action: input.action
    })
  });
  if (!response.ok) {
    const errorBody = await safeJson(response);
    const message = errorBody?.error ?? "Failed to send action";
    throw new Error(message);
  }
}

async function safeJson(response: Response): Promise<{ error?: string } | null> {
  try {
    return (await response.json()) as { error?: string };
  } catch {
    return null;
  }
}
