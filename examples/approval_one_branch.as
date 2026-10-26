agent Janitor {
  permit confirm, delete_file;
  budget calls = 2;

  task cleanup(path: string, careful: bool) -> bool {
    if (careful) {
      let ok = confirm("Delete " + path + "?");
    }
    return delete_file(path);
  }
}
