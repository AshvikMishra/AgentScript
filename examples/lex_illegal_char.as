agent Broken {
  permit llm;
  budget calls = 1;

  task count() -> int {
    let n = 2 # 3;
    return n;
  }
}
