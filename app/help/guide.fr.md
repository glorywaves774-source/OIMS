# Guide d'aide ZENTAVA OIMS

## Se repérer
keywords: menu, naviguer, trouver une page, où est, barre latérale, téléphone, barre d'onglets, mode sombre, mode clair, langue, anglais, navigate, find page, dark mode, language
links: Tableau de bord = workspace.dashboard [dashboard.view]; Mon profil = account.profile
who: tout le monde
Utilisez le menu à gauche (sur téléphone : le bouton ☰ en haut à gauche, ou la barre d'onglets en bas). « Trouver une page » en haut du menu filtre les pages par nom. Le bouton lune/soleil passe du mode sombre au mode clair, et le bouton EN / FR change la langue. Vos choix sont mémorisés.

## Connexion, mot de passe et connexion en deux étapes
keywords: mot de passe, oublié, réinitialiser, connexion, se connecter, bloqué, deux étapes, 2fa, authentification, code de récupération, téléphone perdu, password, forgot, login, two-step
links: Changer le mot de passe = account.change_password; Connexion en deux étapes = account.two_factor
who: tout le monde ; un administrateur de l'organisation peut réinitialiser la connexion en deux étapes d'une autre personne
Pour changer votre mot de passe, ouvrez « Changer le mot de passe ». Si vous l'avez oublié, utilisez « Mot de passe oublié ? » sur la page de connexion ; un lien vous est envoyé par e-mail. Après plusieurs essais erronés, le compte est bloqué un court moment. La connexion en deux étapes demande un code à 6 chiffres d'une application d'authentification ; gardez vos codes de récupération en lieu sûr. Si vous avez perdu votre téléphone, connectez-vous avec un code de récupération, ou demandez à votre administrateur de réinitialiser la connexion en deux étapes après avoir vérifié votre identité.

## Tâches
keywords: tâche, à faire, attribuer, échéance, date limite, en retard, sous-tâche, rappel, task, assign, deadline
links: Tâches = tasks.index [tasks.view]; Nouvelle tâche = tasks.new [tasks.create]
who: tout le monde peut créer des tâches ; modifier la tâche de n'importe qui demande l'autorisation « gérer les tâches »
Ouvrez Tâches pour voir celles qui vous sont attribuées, celles que vous avez créées, ou tout ce que vous pouvez voir. « Nouvelle tâche » en crée une : donnez un titre, une échéance, une priorité et la personne responsable. Elle est prévenue, puis reçoit un rappel avant l'échéance. Les tâches en retard sont signalées en rouge sur le tableau de bord.

## Réunions et comptes rendus
keywords: réunion, compte rendu, ordre du jour, inviter, présence, décisions, points d'action, meeting, minutes
links: Réunions = meetings.index [meetings.view]; Calendrier = comms.calendar [calendar.view]
who: les personnes autorisées à planifier des réunions ; le compte rendu par l'organisateur ou les gestionnaires des réunions
Ouvrez Réunions et choisissez « Planifier une réunion ». Les participants reçoivent une invitation. Après la réunion, rédigez le compte rendu, les décisions et les points d'action ; les points d'action deviennent des tâches pour la personne responsable. Les réunions apparaissent aussi dans le calendrier.

## Congés
keywords: congé, vacances, maladie, congé annuel, jours, absence, approuver un congé, solde, leave, holiday, sick
links: Congés = leave.index [leave.request]; Demander un congé = leave.request_leave [leave.request]; Types de congé = leave.types [leave.manage]
who: chacun demande ses propres congés ; les chefs de département ou les RH les approuvent
Choisissez « Demander un congé », le type et les dates ; les jours ouvrés (du lundi au vendredi) sont comptés automatiquement et votre approbateur est prévenu. Votre solde de l'année est affiché sur la page Congés. Les approbateurs y trouvent les demandes qui les attendent. Les RH définissent les types de congé et les jours par an.

## Documents
keywords: document, fichier, téléverser, dossier, version, partager, approuver un document, télécharger, pdf, word, upload, file
links: Documents = documents.index [documents.view]; Téléverser un document = documents.upload [documents.upload]; Dossiers et catégories = documents.organize [documents.manage]
who: les personnes autorisées à téléverser ; les responsables des archives gèrent dossiers et catégories
Ouvrez Documents et choisissez « Téléverser un document ». Choisissez qui peut le voir (tout le monde, votre département, ou les personnes que vous choisissez). Une nouvelle version conserve l'historique. Certaines catégories demandent une approbation avant que d'autres puissent voir le document. Fichiers acceptés : PDF, Word, Excel, PowerPoint, OpenDocument, CSV, texte et images.

## Courrier (lettres et notes)
keywords: lettre, courrier, note, entrant, sortant, numéro de référence, réponse, enregistrer une lettre, letter, memo
links: Courrier = correspondence.index [correspondence.view]; Enregistrer du courrier = correspondence.new [correspondence.create]
who: les responsables des archives enregistrent ; la personne à qui une lettre est attribuée y répond
Enregistrez les lettres entrantes et sortantes et les notes internes ; chacune reçoit un numéro de référence comme IN/2026/0001. Attribuez une lettre à quelqu'un avec une date de réponse ; un rappel lui est envoyé. L'historique du circuit montre qui l'a traitée.

## Messages, notifications et annonces
keywords: message, discussion, notification, annonce, nouvelles, non lu, cloche, chat, announcement
links: Messages = comms.inbox [messages.use]; Notifications = comms.notifications; Annonces = comms.announcements [announcements.view]
who: tout le monde ; publier des annonces demande l'autorisation correspondante
Les messages sont des conversations privées entre collègues. La cloche affiche les notifications (attributions, approbations, rappels). Les annonces sont des nouvelles pour toute l'organisation ou un département.

## Personnel et RH
keywords: personnel, employé, rh, contrat, fiche du personnel, enregistrer, départ, mutation, formation, performance, annuaire, staff, hr
links: Annuaire du personnel = staff.index [staff.view]
who: les responsables RH enregistrent et tiennent les fiches
Les RH enregistrent le personnel avec les détails d'emploi, contrats et documents, formations, évaluations et mutations. Les fiches ne sont visibles que par les personnes autorisées à voir les dossiers RH. Au départ d'une personne, les RH enregistrent la sortie et la fiche passe en lecture seule.

## Présence
keywords: présence, présent, absent, registre, présence du jour, attendance
links: Présence = attendance.register [attendance.record]
who: les personnes autorisées à enregistrer la présence (souvent les chefs de département)
Ouvrez Présence, cochez qui est présent, absent ou en congé ce jour-là, et enregistrez.

## Départements, utilisateurs et rôles
keywords: département, utilisateur, inviter, rôle, autorisation, accès, administrateur, ajouter un utilisateur, retirer, suspendre, user, role, permission
links: Départements = departments.index [departments.view]; Utilisateurs = workspace.users [users.view]; Inviter un utilisateur = workspace.user_invite [users.invite]; Rôles = workspace.roles [roles.view]
who: les administrateurs de l'organisation
Les administrateurs invitent les utilisateurs et donnent un rôle à chacun. Les rôles standard sont tenus à jour ; pour en modifier un, dupliquez-le en rôle personnalisé. Chaque autorisation peut être limitée à toute l'organisation, au département de la personne ou à ses propres fiches.

## Paramètres de l'organisation
keywords: paramètres, logo, profil de l'organisation, devise, fuseau horaire, exercice, settings
links: Paramètres = workspace.settings [organization.view]
who: les administrateurs de l'organisation
Les paramètres contiennent le profil de l'organisation, le logo, la devise principale, le fuseau horaire, l'exercice et les listes du bureau.

## Programmes
keywords: programme, enregistrer un programme, cadre de résultats, cadre logique, indicateurs, plan de travail, activités, jalons, bailleur, budget, program
links: Programmes = programmes.index [programmes.view]; Enregistrer un programme = programmes.new [programmes.create]
who: les directeurs et responsables de programme
Enregistrez un programme avec son objectif, ses dates, son responsable et son budget approuvé. Construisez ensuite le cadre de résultats (objectif global, objectifs, effets, produits) avec des indicateurs, les plans de travail et activités, les jalons et les lignes budgétaires. Un programme est approuvé avant toute dépense ; ensuite, les changements de budget passent par une révision budgétaire.

## Projets
keywords: projet, structure de découpage, livrable, risque, problème, clôture, clôturer un projet, composante, project, wbs
links: Projets = projects.index [projects.view]; Enregistrer un projet = projects.new [projects.create]
who: les chefs de projet
Un projet peut faire partie d'un programme ou être indépendant. Planifiez-le avec des composantes, activités, tâches et livrables, tenez les registres des risques et des problèmes, et clôturez-le avec la liste de clôture et son approbation.

## Budget, dépenses et approbations
keywords: budget, dépense, dépenser, paiement, engagement, approuver une dépense, ligne budgétaire, révision budgétaire, finances, expenditure
links: Aperçu des finances = finance.overview [finance.view]
who: les responsables financiers enregistrent et approuvent ; une autre personne doit approuver ce que quelqu'un a enregistré
Une dépense est enregistrée sur une ligne budgétaire d'un programme ou projet et ne compte qu'après approbation par une autre personne habilitée. Les engagements réservent l'argent pour les commandes et contrats. L'aperçu des finances montre budgets, dépenses et ce qui attend votre approbation.

## Taux de change
keywords: taux de change, devise, convertir, dollar, euro, cedi, total combiné, exchange rate, currency
links: Taux de change = finance.rates [finance.view]
who: les responsables financiers (autorisation « fixer les taux de change »)
Sous Finances → Taux de change, l'équipe financière enregistre des taux datés (par exemple 1 USD = 15,40 GHS à partir du 1er novembre). Ils servent aux totaux combinés dans la devise de l'organisation ; les dépenses d'une période de rapport utilisent le taux du jour de chaque paiement. Une devise sans taux est exclue et nommée.

## Achats
keywords: achat, acheter, demande d'achat, devis, bon de commande, fournisseur, réception, appel d'offres, procurement, purchase
links: Achats = procurement.index [procurement.view]; Nouvelle demande d'achat = procurement.new [procurement.request]; Fournisseurs = procurement.suppliers [procurement.view]
who: toute personne autorisée à émettre des demandes d'achat ; approbation par un responsable ; le service des achats gère devis et commandes
Émettez une demande d'achat sur une ligne budgétaire. Après approbation, le service des achats enregistre les devis (un, trois, ou un appel d'offres selon le montant), prépare le bon de commande et enregistre les réceptions. Le paiement est possible pour ce qui a été reçu.

## Biens
keywords: bien, équipement, ordinateur, véhicule, moto, étiquette, attribuer un bien, mise au rebut, inventaire, asset
links: Registre des biens = assets.index [assets.view]; Enregistrer un bien = assets.edit [assets.manage]
who: les responsables logistique et biens ; les mises au rebut sont approuvées par une autre personne
Les articles achetés comme biens sont ajoutés automatiquement au registre. Chaque bien a une étiquette, un détenteur, un lieu et des contrôles. Demandez une mise au rebut quand un bien est perdu, cassé ou donné ; une autre personne l'approuve.

## Bénéficiaires
keywords: bénéficiaire, inscrire, inscription, consentement, ménage, service, présence, doublon, anonymiser, beneficiary
links: Bénéficiaires = beneficiaries.index [beneficiaries.view]; Inscrire un bénéficiaire = beneficiaries.new [beneficiaries.register]; Ménages = beneficiaries.households [beneficiaries.view]
who: les agents de terrain et responsables MEAL inscrivent ; les données personnelles seulement pour les personnes autorisées
Inscrivez une personne une seule fois (le système signale les doublons probables), enregistrez son consentement, puis inscrivez-la à un programme ou projet et enregistrez les services et présences. Sans consentement en cours, rien de nouveau ne peut être enregistré. Les numéros de téléphone et de pièce sont stockés chiffrés.

## MEAL, indicateurs et collecte de données
keywords: meal, suivi, évaluation, indicateur, résultat, vérifier, collecte de données, formulaire, enquête, réponses, monitoring
links: Aperçu MEAL = meal.dashboard [meal.view]; Formulaires de collecte = meal.forms [meal.view]
who: les responsables MEAL définissent les indicateurs et vérifient ; le personnel de terrain déclare et collecte
Déclarez les résultats des indicateurs ; ils ne comptent qu'après vérification par une autre personne que le déclarant. Les formulaires de collecte sont des enquêtes et listes de contrôle que votre équipe remplit ; les réponses sont contrôlées par une deuxième personne.

## Retours et plaintes
keywords: retour, plainte, suggestion, protection, communauté, ligne d'assistance, page publique, feedback, complaint
links: Retours = feedback.index [feedback.view]; Enregistrer un retour = feedback.new [feedback.record]; Page publique de retours = feedback.settings [feedback.manage]
who: toute personne autorisée à enregistrer des retours ; les dossiers sensibles seulement pour l'équipe de protection
Enregistrez les retours reçus des communautés, attribuez-les, répondez et clôturez avec la satisfaction de la personne. Les signalements d'abus, de fraude ou d'inconduite sont confidentiels et vont uniquement à l'équipe de protection. Une page publique permet d'envoyer un retour sans compte.

## Rapports et exports
keywords: rapport, exporter, excel, csv, pdf, rapport au bailleur, graphique, analyse, télécharger, report, export
links: Rapports = analytics.index [reports.view]
who: les personnes autorisées à voir les rapports
Les rapports couvrent le portefeuille, les indicateurs, le budget et les dépenses, les bailleurs, les activités, les bénéficiaires, les retours, les achats, les biens et le personnel, pour toute période, et se téléchargent en Excel, CSV ou PDF. Chacun ne montre que ce que vous pouvez voir. Les rapports narratifs des programmes et projets se rédigent dans leur onglet Rapports et sont approuvés.

## Abonnement et facturation
keywords: abonnement, formule, facture, payer, facturation, paiement, en retard, lecture seule, subscription, invoice, billing
links: Facturation = billing.index [billing.view]
who: les administrateurs de l'organisation
La page Facturation montre la formule, l'utilisation et les factures. Payez en ligne ou par virement avec le numéro de facture comme référence. Si une facture reste impayée après le délai de grâce, l'espace passe en lecture seule jusqu'au paiement ; rien n'est supprimé.

## Accès du support Kayron
keywords: support, kayron, assistance, demande d'accès, accès du support
links: Accès du support = workspace.support [support.view]
who: les administrateurs de l'organisation approuvent
Le personnel de Kayron peut seulement consulter votre espace (jamais le modifier), pour une durée limitée, après votre approbation, et chaque page ouverte est enregistrée dans votre journal d'audit.

## Console de la plateforme Kayron
keywords: plateforme, organisations, approuver une organisation, formules, personnel de la plateforme, facturation plateforme, platform
links: Tableau de bord de la plateforme = platform.dashboard [platform]; Organisations = platform.organizations [platform]; Formules d'abonnement = platform.plans [platform]; Facturation = platform_billing.index [platform]
who: le personnel de la plateforme Kayron uniquement
La console liste les organisations (approuver, suspendre, créer), les formules d'abonnement, le personnel de la plateforme, la facturation et le journal d'audit de la plateforme.
