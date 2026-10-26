agent Scout {
  permit web_search, llm;
  budget calls = 4;

  task scout(a: string, b: string, c: string) -> string {
    let ra = web_search(a);
    let rb = web_search(b);
    let rc = web_search(c);
    return llm(ra[1] + " | " + rb[1] + " | " + rc[1]);
  }
}
