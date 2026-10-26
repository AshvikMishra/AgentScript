agent Greedy {
  permit web_search, llm;
  budget calls = 3;

  task dig(topic: string) -> string {
    let a = web_search(topic);
    let b = web_search(a[1]);
    let c = web_search(b[1]);
    return llm(c[1]);
  }
}
