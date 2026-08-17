# Огляд залежностей

## Встановлений стан

| Пакет | Версія | Стан |
|---|---:|---|
| PyYAML | 6.0.3 | direct, current constraint |
| pypdf | 6.13.3 | direct; PyPI вже має 6.14.x, але update не потрібен без тестів |
| python-docx | 1.2.0 | direct |
| lxml | 6.1.1 | transitive |
| restic | 0.19.0 | system binary, актуальний release на дату аудиту |

`pip check`: no broken requirements. OSV API query для чотирьох встановлених Python packages не повернув advisories на дату аудиту. Це point-in-time перевірка, не гарантія відсутності майбутніх CVE.

Первинні джерела: [PyYAML PyPI](https://pypi.org/project/PyYAML/), [pypdf PyPI](https://pypi.org/project/pypdf/), [python-docx PyPI](https://pypi.org/project/python-docx/), [restic 0.19.0 release](https://github.com/restic/restic/releases/tag/v0.19.0), [OSV API](https://google.github.io/osv.dev/api/).

## Проблеми

- Немає lock/constraints з hashes.
- `install.ps1` автоматично оновлює pip і встановлює mutable ranges.
- Немає CI matrix для підтримуваних Python.
- `pyproject.toml` version 1.0.0 не узгоджена з документацією v1.1.
- System dependency restic не pin/check-summed проєктом; doctor лише знаходить executable.

## Рекомендації

1. Не оновлювати залежності під час виправлення функціональних defects.
2. Окремим PR створити reproducible constraints/lock із hashes.
3. Додати scheduled dependency review, але update лише після regression suite і restore drill.
4. Верифікувати trusted source/hash restic binary або документувати winget source/package ID.

