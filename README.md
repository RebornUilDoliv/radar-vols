# Eunodia, le radar de vols pas chers

Chaque heure, cet outil surveille les vols aller-retour au départ de Paris et t'envoie un e-mail quand il trouve un bon prix. Il est prévu pour rester gratuit.

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

Dans l'onglet **Actions**, ouvre **Radar de vols**, puis clique sur **Run workflow**. Ensuite, l'outil relève les prix chaque heure et consulte Google Flights au plus toutes les 12 heures. Ça compense les retards de GitHub.

Les horaires de GitHub peuvent être retardés ou sautés. Le serveur Cloudflare du dossier `worker/` lance donc aussi le radar chaque heure, avec le secret `GITHUB_DISPATCH_TOKEN` : une clé GitHub limitée à ce dépôt, avec la seule permission **Actions** en lecture et écriture. Si les deux planifications se suivent, la seconde ne refait pas de relevé.

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

## Le site public

Après chaque passage, le radar écrit les prix Travelpayouts dans `docs/prices.json`, puis `build_site.py` génère le site : accueil, liste des vols, une page par destination, plan du site. Les budgets et les prix vérifiés via SerpApi ne sont jamais publiés.

Le moteur de recherche renvoie vers Aviasales avec le lien partenaire. Le site n'utilise ni script partenaire ni cookie.

Les pages `/vols-pas-chers/` regroupent les prix par mois, par région et par budget. Une sélection n'est publiée que si elle couvre au moins 3 villes.

Pour mesurer l'audience sans cookie, indique l'identifiant public de Cloudflare Web Analytics dans `analytics_token` de `config.toml`.

Le relevé mondial (`world.py`) cherche les prix depuis les villes de `[world]` dans `config.toml`, au plus une fois par jour. Le site publie une page par ville de départ, et une page par route pour les destinations les plus desservies.

La page `/vols/` est l'outil « Où partir » : elle lit les prix de la ville choisie dans `docs/assets/routes/`. La page `/test-reservation/` reste accessible par son lien direct, mais n'est plus dans le menu.

Le nom et l'adresse du site se changent dans la section `[site]` de `config.toml`.

## La version de test de réservation

La page `/test-reservation/` montre un parcours de réservation complet. Elle n'apparaît pas dans le menu et elle est cachée aux moteurs de recherche. Par défaut, elle fonctionne en mode démonstration, avec des données simulées dans le navigateur.

Pour la brancher sur l'environnement de test de Duffel, déploie le dossier `worker/` sur Cloudflare Workers, ajoute le secret `DUFFEL_TEST_TOKEN`, puis indique l'adresse du serveur dans `test_api` de `config.toml`. Le serveur refuse tout jeton qui ne commence pas par `duffel_test_`.

Pour afficher de vrais prix, ajoute le secret `DUFFEL_LIVE_SEARCH_TOKEN`, qui doit commencer par `duffel_live_`. Le serveur s'en sert uniquement pour chercher : la réservation reste alors simulée et aucune commande n'est envoyée à Duffel.

Cette version ne vend rien. Ne la passe pas en réel sans avoir validé les obligations légales, l'assurance, la garantie, le paiement et le service client.

## Limites

- Les prix Travelpayouts viennent d'un cache alimenté par les recherches d'autres utilisateurs. Il peut donc rater des offres ou couvrir certaines destinations moins bien.
- Le budget est calculé pour un adulte en aller-retour, sans options comme les bagages.
- Vérifie toujours le prix final sur le site de réservation.
