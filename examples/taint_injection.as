agent Assistant {
  permit web_search, llm, sanitize, send_email, confirm;
  budget calls = 5;

  task report(topic: string) -> bool {
    let raw = web_search(topic);
    let summary = llm("Summarize: " + raw[0]);
    if (confirm("Send report?")) {
      return send_email("me@example.com", summary);
    }
    return false;
  }
}
