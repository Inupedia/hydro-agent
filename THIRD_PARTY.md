# Third-party hydrologic runtimes

## hydromodel (XAJ)

- Repository: https://github.com/OuyangWenyu/hydromodel
- Locked commit: `89d7a8ed1d72ce4fffbbd9897490b089382ecbac`
- License: GPL-3.0
- Use in Hydro-Agent: the pinned XAJ numerical implementation (`hydromodel.models.xaj.xaj`) only. Hydro-Agent does not vendor or reimplement that solver; the sandbox adapter prepares frozen snapshot/scheme files and a child process calls the locked upstream function.
