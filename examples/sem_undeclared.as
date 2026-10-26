agent Broken {
  permit llm;
  budget calls = 1;

  task answer() -> string {
    return x;
  }
}
