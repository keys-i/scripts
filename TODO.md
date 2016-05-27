# TODO

- [x] Commit the interactive C# dashboard on `cs`:

  ```sh
  git add .github/workflows/test.yml .gitignore README.md TODO.md \
    dev/tui/Scripts.Tui.csproj dev/tui/Program.cs docs/CONTRIBUTING.md \
    sys/linux/clean sys/linux/clean.help sys/macos/clean.help \
    sys/windows/clean.ps1.help && \
    git -c commit.gpgsign=false bkcommit '2016-05-27T16:04:00+10:00' \
      -m 'add: interactive C# script dashboard'
  ```

- [x] Keep workflow changes on the separate `actions` branch:

  ```sh
  git add .github/workflows/test.yml TODO.md && \
    git -c commit.gpgsign=false bkcommit '2016-05-27T16:22:00+10:00' \
      -m 'update: separate C# and Actions branches'
  ```
