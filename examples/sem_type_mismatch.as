agent Broken {
  permit web_search;
  budget calls = 1;

  task find() -> list<string> {
    return web_search(42);
  }
}
