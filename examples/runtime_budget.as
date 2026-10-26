agent Poller {
  permit web_search;
  budget calls = 3;

  task poll(topic: string, times: int) -> int {
    repeat times {
      let r = web_search(topic);
    }
    return times;
  }
}
