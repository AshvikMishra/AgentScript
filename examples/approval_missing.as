agent Janitor {
  permit confirm, delete_file;
  budget calls = 3;

  task purge(path: string, force: bool) -> bool {
    if (force) {
      return delete_file(path);
    }
    if (confirm("Delete " + path + "?")) {
      return delete_file(path);
    }
    return false;
  }
}
