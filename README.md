# PixelCarte (version Python)

PixelCarte est une application Flask avec base SQLite : comptes, créations enregistrées et formulaire de contact. Le traitement des images reste dans le navigateur. L'interface est servie depuis `static/index.html`.

## Lancer en local

```bash
python -m venv venv
. venv/bin/activate        # Windows : venv\\Scripts\\activate
pip install -r requirements.txt
python app.py              # puis http://localhost:8000
```

## Démarrer avec Gunicorn

```bash
gunicorn -b 0.0.0.0:${PORT:-8000} app:app
```

## Variables d'environnement

Toutes sont facultatives sauf si la fonctionnalité correspondante est utilisée :

- `SERVER_PORT` ou `PORT` : port d'écoute local (8000 par défaut).
- `DATA_DIR` : dossier de la base SQLite et de la clé de session (par défaut `./data`). Conserver ce dossier entre les redémarrages.
- `SECRET_KEY` : clé des sessions. Si elle n'est pas définie, une clé aléatoire est créée et conservée dans `DATA_DIR/secret.key`.
- `ADMIN_KEY` : active `/admin/messages?key=...` pour consulter les messages du formulaire.
- `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASS`, `MAIL_TO` : configuration facultative de l'envoi des messages par e-mail. L'envoi se fait lorsque `SMTP_HOST` et `MAIL_TO` sont définis.

Ne placez jamais de valeurs secrètes dans le dépôt. Configurez ces variables dans l'environnement de l'hébergeur ; ne commitez pas de fichier `.env`.

## Déploiement

Les fichiers `app.py`, `requirements.txt` et le dossier `static/` doivent être à la racine du projet déployé. Le point d'entrée Gunicorn est `app:app`. L'application crée sa base SQLite dans `DATA_DIR` (ou `./data`) au démarrage.

## Structure du dépôt

```text
pixelcarte/
├── app.py
├── requirements.txt
├── README.md
├── LICENSE
├── .gitignore
└── static/
    └── index.html
```
