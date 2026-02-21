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

```python
sabormirandiano.settings.cursos=["1-A", "1-B", "2-A", "2-B", "3-A", "3-B", "4-A", "4-B", "5-A", "5-B", "6-A", "6-B", "7-A", "7-B", "8-A", "8-B", "I-A", "I-B", "II-A", "II-B", "III-A", "III-B", "IV-A", "IV-B"]
```

## Para cambiar

- [ ] Quitar "menuopciones" desde el formulario de platos
- [ ] Agregar ayudas en los campos de texto al crear itemes
- [x] Agregar Stock en menú diario
