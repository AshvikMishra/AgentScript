agent Reader {
  permit web_search;
  budget calls = 1;

  task tenth(topic: string) -> string {
    let results = web_search(topic);
    return results[9];
  }
}
