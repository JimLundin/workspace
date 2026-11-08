async (evaluate, limit) => {
    const value = await evaluate();
    const text = JSON.stringify(value ?? null) ?? String(value);
    return text.length > limit ? text.slice(0, limit - 30) + '\n[output truncated]' : text;
}
