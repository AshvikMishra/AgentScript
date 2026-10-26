agent Researcher {
  permit web_search, llm;
  budget calls = 4;

  task research(topic: string) -> string {
    let pages = 2 * 3;
    let first = web_search(topic);
    let again = web_search(topic);
    let debug = false;
    if (debug) {
      return llm("debug");
    }
    return llm("Compare: " + first[1] + " / " + again[2]);
  }
}
