agent Broken {
  permit web_search;
  budget calls = 1;

  task find(topic: string) -> list<string> {
    let a = web_search(topic)
    return a;
  }
}
