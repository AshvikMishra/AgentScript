agent Broken {
  permit llm;
  budget calls = 1;

  task check(flag: bool) -> bool {
    if (flag) {
      return true;
    }
  }
}
