# Second brain

Vault personale in Markdown, versionato con git.
Remote principale: il repo bare sul server (`brain.git`). Se configurato, un mirror automatico su GitHub.

Questo file contiene le regole per Claude: adattalo a come prendi appunti.

## Regole assolute
- **Niente credenziali**: password, token, chiavi API, chiavi private. Al loro posto scrivi dove si trovano (es. "nel password manager, voce X").
- Non cancellare né riscrivere note esistenti senza chiedere. Aggiungere va bene.

## Struttura (PARA)
- `inbox/`: cattura grezza (bot Telegram e note veloci). File `AAAA-MM-GG-hhmmss.md`, allegati in `inbox/attachments/`.
- `projects/`: cose con una fine. Quando si chiudono vanno in `archive/`.
- `areas/`: responsabilità continue, senza scadenza.
- `resources/`: conoscenza per argomento, riusabile.
- `archive/`: progetti chiusi, aree abbandonate.

## Convenzioni
- Un file per argomento, non per singolo pensiero. Se un file cresce troppo diventa una cartella con lo stesso nome.
- Nomi file in kebab-case, senza date (tranne in `inbox/`).
- Link interni con doppie quadre e nome file (es. `[ [nome-file] ]` senza spazi).

## Frontmatter e tag
- `created` (AAAA-MM-GG) e `type` obbligatori. `type`: `tool` | `concetto` | `persona` | `progetto` | `area`.
- `tags`: kebab-case minuscoli, al massimo 3, per temi trasversali. Prima di inventarne uno nuovo, riusa quelli esistenti.
- `source` (telegram, conversazione, web) e `forwarded_from` quando la nota nasce da un inbox.

## Rispondere a domande sul vault
Cerca con ripgrep (`rg -i`), leggi i file pertinenti, cita i percorsi dei file da cui prendi le informazioni.
Se l'informazione non c'è, dillo: non inventare.
