agent Reader {
  permit llm;
  budget calls = 2;

  task summarize(path: string) -> string {
    let text = read_file(path);
    return llm(text);
  }
}
