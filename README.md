# Radar de vols pas chers

Deux fois par jour, cet outil surveille les vols aller-retour au départ de Paris et t'envoie un e-mail quand il trouve un bon prix. Il est prévu pour rester gratuit.

## Comment il fonctionne

1. **Repérage :** Travelpayouts donne les prix récents pour tes destinations et les 9 prochains mois.
2. **Sélection :** un prix est retenu s'il passe sous ton budget, ou s'il est au moins 25 % sous son prix habituel.
3. **Vérification :** les meilleures offres sont contrôlées sur Google Flights via SerpApi, avec 4 contrôles maximum par passage et 240 par mois.
4. **Alerte :** tu reçois un seul e-mail récapitulatif, et la même offre n'est pas répétée pendant 7 jours sauf nouvelle baisse.

Le « prix habituel » est calculé à partir de l'historique du radar. Cette détection démarre donc après 6 jours de relevés pour un même mois et une même destination.

Si le quota SerpApi est épuisé ou si la vérification échoue, l'offre peut quand même être envoyée, avec la mention « À confirmer ».

## Mise en route

### 1. Préparer les comptes gratuits

| Service | À récupérer |
|---|---|
| [Travelpayouts](https://www.travelpayouts.com/) | Ton token API, dans ton profil |
| [SerpApi](https://serpapi.com/users/sign_up) | Ta clé API |
| [Gmail](https://myaccount.google.com/apppasswords) | Un mot de passe d'application de 16 lettres, après avoir activé la validation en deux étapes |

Gmail sert uniquement à envoyer les alertes. Tu peux les recevoir sur n'importe quelle adresse grâce à `MAIL_TO`.

### 2. Comprendre ce qui est public

Ce dépôt est **public** : le code, `config.toml` et l'historique des prix sont visibles par tout le monde. N'y écris jamais de clé, de mot de passe ou d'information personnelle.

### 3. Ajouter les secrets

Dans le dépôt, ouvre **Settings → Secrets and variables → Actions**, puis ajoute :

| Secret | Valeur |
|---|---|
| `TRAVELPAYOUTS_TOKEN` | Ton token Travelpayouts |
| `SERPAPI_KEY` | Ta clé SerpApi |
| `SMTP_USER` | Ton adresse Gmail |
| `SMTP_PASSWORD` | Le mot de passe d'application Gmail |
| `MAIL_FROM` | Ton adresse Gmail |
| `MAIL_TO` | L'adresse qui reçoit les alertes |

Ne mets jamais ces valeurs dans un fichier du dépôt.

### 4. Lancer un premier passage

Dans l'onglet **Actions**, ouvre **Radar de vols**, puis clique sur **Run workflow**. Ensuite, l'outil tournera tout seul vers 7 h 17 et 17 h 17 en hiver, et une heure plus tard en été. GitHub peut parfois lancer le passage avec du retard.

Pour tester uniquement l'envoi, coche **Envoyer seulement un e-mail d'exemple** avant de lancer **Run workflow**. Ce test n'utilise aucune recherche SerpApi.

Si un passage échoue, GitHub t'avertit et le journal du passage indique quoi corriger. Vérifie aussi tes courriers indésirables lors des premières alertes.

## Modifier les réglages

Tout se règle dans [config.toml](config.toml) :

- `max_price` : le budget maximum de chaque groupe ;
- `min_days` et `max_days` : la durée du séjour ;
- `countries` : les pays surveillés ;
- `cities` : les villes vérifiées mois par mois ;
- `deal_drop` : la baisse nécessaire pour parler de bonne affaire ;
- `market_low_only = true` : remplace `max_price` et n'alerte que si Google Flights juge le prix bas. Sans vérification possible, aucune alerte n'est envoyée.

Les budgets actuels sont des points de départ à adapter.

## Tester sur ton Mac (facultatif)

```bash
export SSL_CERT_FILE=/etc/ssl/cert.pem
```

```bash
export TRAVELPAYOUTS_TOKEN="ton-token"
```

```bash
python3 radar.py --dry-run
```

`--dry-run` affiche les offres sans envoyer d'e-mail, sans sauvegarder et sans utiliser SerpApi.

Pour vérifier les tests automatiques :

```bash
python3 -m unittest test_radar
```

## Limites

- Les prix Travelpayouts viennent d'un cache alimenté par les recherches d'autres utilisateurs. Il peut donc rater des offres ou couvrir certaines destinations moins bien.
- Le budget est calculé pour un adulte en aller-retour, sans options comme les bagages.
- Vérifie toujours le prix final sur le site de réservation.
