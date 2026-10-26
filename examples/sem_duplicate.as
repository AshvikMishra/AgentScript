agent Broken {
  permit llm;
  budget calls = 1;

  task twice(topic: string) -> string {
    let a = topic;
    let a = topic;
    return a;
  }
}
