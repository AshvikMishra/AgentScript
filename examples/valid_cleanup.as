agent Janitor {
  permit confirm, delete_file;
  budget calls = 2;

  task cleanup(path: string) -> bool {
    let ok = confirm("Delete " + path + "?");
    if (ok) {
      return delete_file(path);
    }
    return false;
  }
}
