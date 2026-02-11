# SaborMirandiano

Private project

```bash
poetry run flask roles create admin -d "Admin Group"
poetry run flask roles create apoderado -d "Grupo Apoderados"
poetry run flask roles create pos -d "Staff de Casino"

poetry run flask users create -a email:mariofix@proton.me -u mariofix
poetry run flask users create -a email:mario@fonotarot.com -u apoderado
poetry run flask users create -a email:ruurd@156.cl -u ruurd

poetry run flask roles add mariofix@proton.me admin
poetry run flask roles add mariofix@proton.me pos
poetry run flask roles add mario@fonotarot.com apoderado
poetry run flask roles add ruurd@156.cl admin
poetry run flask roles add ruurd@156.cl pos
poetry run flask roles add ruurd@156.cl apoderado

SCREEN -S app poetry run flask run -h 10.0.0.2 -p 3010 --debug --reload
```
