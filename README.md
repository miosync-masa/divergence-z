# Divergence-Z 🌀

> **"Don't Kill the Tsundere"**
> — Action-Preserving Translation for Fictional Speech

🇬🇧 [English](#english) | 🇫🇷 [Français](#français)

---

## 💡 No API? No Problem!

**You don't need to be a developer to use these ideas.**

This repository includes Python scripts for automation, but the core concepts work with any chat-based LLM (ChatGPT, Claude, etc.). The prompts and persona YAMLs can be copy-pasted directly into a chat interface.

**Want to try it yourself?**
1. Copy a persona YAML from `personas/`
2. Paste it into ChatGPT/Claude with your line to translate
3. Ask it to preserve the *action*, not just the meaning

The magic is in the **prompt engineering**, not the code. Give it a try! 🚀

---

## 💡 Pas d'API ? Pas de problème !

**Vous n'avez pas besoin d'être développeur pour utiliser ces idées.**

Ce dépôt contient des scripts Python pour l'automatisation, mais les concepts de base fonctionnent avec n'importe quel LLM en mode chat (ChatGPT, Claude, etc.). Les prompts et les YAMLs de persona peuvent être copiés-collés directement dans une interface de chat.

**Vous voulez essayer ?**
1. Copiez un persona YAML depuis `personas/`
2. Collez-le dans ChatGPT/Claude avec votre réplique à traduire
3. Demandez-lui de préserver l'*action*, pas seulement le sens

La magie est dans le **prompt engineering**, pas dans le code. Essayez ! 🚀

---

# English

## The Problem You Already Know

You've seen it. That moment when your favorite character's most powerful line gets translated and... something dies.

**Rem's confession (Re:Zero):**

```
Japanese: 「レムは、スバルくんを、愛しています」

DeepL:    "Rem loves Subaru."
```

Wait. That's not a confession anymore. **That's a Wikipedia summary.** 💀

The meaning is "correct." But the *action*—a direct, face-to-face confession of love—became third-person narration. The intimacy? Gone. The vulnerability? Gone. The scene where Rem looks Subaru in the eyes and bares her soul? Now it reads like someone describing the scene from outside.

**This is the problem we're solving.**

## What is Z-Axis Translation?

Standard translation preserves **meaning** (what is said).

Z-Axis translation preserves **action** (what the line *does*).

| Layer | What it is | Language-dependent? |
|-------|------------|---------------------|
| **Text Layer** | Words, grammar, syntax | ✅ Yes |
| **Action Layer** | Confess, threaten, deflect, deny, vow... | ❌ No |

A translation succeeds when the **action** survives, even if the surface form changes completely.

### The Confession Test

```
Original action:  DIRECT CONFESSION (speaker → listener, face-to-face)
DeepL action:     REPORTED STATEMENT (narrator → audience, describing)

Same meaning. Completely different action.
```

## Why Not Just Use LLMs?

"Can't GPT/Claude just translate better?"

Yes and no. LLMs *can* produce beautiful translations. But they don't know:
- Who this character is (their conflicts, speech patterns, emotional tendencies)
- Who they're talking to (and what that relationship means)
- What emotional state they're in right now
- What this line is supposed to *do* to the listener

Without this context, even the best LLM will sometimes:
- Turn confessions into narration
- Flatten tsundere deflection into plain denial
- Lose the "leak then overwrite" pattern that makes a character feel real

**Z-Axis Translation gives LLMs the context they need.**

## How It Works

### 1. Persona Engineering

Each character gets a **persona YAML** capturing:
- **Conflict axes**: "admit feelings vs. protect self", "duty vs. desire"
- **Bias patterns**: how emotions surface (e.g., Tsun→Dere→Overwrite)
- **Triggers**: what makes them react (being called "assistant", being thanked)
- **Risk flags**: where translations typically fail for this character

### 2. Translation Pipeline (3 Steps)

```
STEP 1: Hamiltonian Extraction
         → What conflicts are active? What's the emotional state?

STEP 2: Interference Pattern Analysis  
         → How do those conflicts manifest in speech?
         → Hesitation? Denial? Self-correction? Emotional leak?

STEP 3: Z-Axis Preserving Translation
         → Generate target language text that performs the SAME ACTION
```

### 3. Evaluation: IAP & ZAP

We built two evaluators to measure what matters:

| Metric | What it measures |
|--------|------------------|
| **IAP** (Illocutionary Act Preservation) | Does the translation perform the same speech acts? (confess, refuse, threaten...) |
| **ZAP** (Z-Axis Preservation) | Does it still sound like the character? Is the emotional intensity preserved? |

## Results: What We Found

### Experiment 1: Rem's Confession (Re:Zero)

| System | Address Mode | IAP Score | What happened |
|--------|--------------|-----------|---------------|
| DeepL | direct → **reported** | 0.51 | Confession became narration |
| Z-Axis | direct → **direct** | 0.76 | Preserved face-to-face confession |

### Experiment 2: Kurisu's Tsundere (Steins;Gate)

Same line: 「別に...あんたのためじゃないから」

| Context | Z-Axis Output | Action |
|---------|---------------|--------|
| Daily | "N-not that it's for you or anything." | Standard deflection |
| Jealous | "I— I mean, it's not like I did it for you, okay?" | Emotion leak → overwrite |
| Monologue | "It's not for him... I mean— it's *not*." | Self-deception (double denial) |

**The same words perform different actions depending on context.**

### Experiment 3: Luffy's Ultimatum (One Piece)

"If you tell us, I quit being a pirate."

Tested EN→FR→EN round-trip. **The ultimatum survived.** (Explicit actions are robust.)

But the refusal framing matters:
- ❌ "I don't care where the treasure is" (apathy)
- ✅ "I don't wanna hear where the treasure is" (boundary-setting to protect the journey)

Same meaning. Different character voice.

## Quick Start

```bash
# Setup
pip install anthropic openai pyyaml python-dotenv requests

# Create .env
ANTHROPIC_API_KEY=sk-ant-xxxxx   # For persona generation
OPENAI_API_KEY=sk-xxxxx          # For translation & evaluation

# Generate a persona
python persona_generator.py --name "レム" --source "Re:Zero" --desc "献身的メイド"

# Translate with Z-axis preservation
python z_axis_translate.py --config requests/rem_test.yaml

# Evaluate
python iap_evaluator.py -o "スバルくんが良いんです" -t "You're the one I choose, Subaru-kun"
python zap_evaluator.py --config requests/rem_test.yaml --translated "I love you, Subaru-kun"
```

## Paper

This repository accompanies our practice report submitted to the **Journal of Audiovisual Translation (JAT)**:

> **Translation as Action Preservation (TAP): Evaluating Anime/Manga Translation Beyond Meaning**
>
> We propose evaluating translations not by semantic similarity alone, but by whether they preserve the *illocutionary action*—what the line does to the listener and the scene.

📄 [Read the full paper](#) *(link to be added upon publication)*

## Philosophy

> "We didn't build this because machines translate badly.
> We built this because **even good translations can kill characters**."

The goal isn't to replace translators. It's to externalize one part of expert practice: **keeping the action intact across languages**.

---

# Français

## Le problème que vous connaissez déjà

Vous l'avez vécu. Ce moment où la réplique la plus puissante de votre personnage préféré est traduite et... quelque chose meurt.

**La déclaration de Rem (Re:Zero) :**

```
Japonais: 「レムは、スバルくんを、愛しています」

DeepL:    "Rem loves Subaru." / "Rem aime Subaru."
```

Attendez. Ce n'est plus une déclaration d'amour. **C'est un résumé Wikipédia.** 💀

Le sens est « correct ». Mais l'*action*—une déclaration directe, face à face—est devenue une narration à la troisième personne. L'intimité ? Disparue. La vulnérabilité ? Disparue. Cette scène où Rem regarde Subaru dans les yeux et lui ouvre son cœur ? Maintenant, on dirait que quelqu'un décrit la scène de l'extérieur.

**C'est le problème que nous résolvons.**

## Qu'est-ce que la traduction Z-Axis ?

La traduction standard préserve le **sens** (ce qui est dit).

La traduction Z-Axis préserve l'**action** (ce que la réplique *fait*).

| Couche | Ce que c'est | Dépend de la langue ? |
|--------|--------------|------------------------|
| **Couche Texte** | Mots, grammaire, syntaxe | ✅ Oui |
| **Couche Action** | Déclarer, menacer, esquiver, nier, jurer... | ❌ Non |

Une traduction réussit quand l'**action** survit, même si la forme de surface change complètement.

### Le test de la déclaration

```
Action originale:    DÉCLARATION DIRECTE (locuteur → auditeur, face à face)
Action DeepL:        ÉNONCÉ RAPPORTÉ (narrateur → public, description)

Même sens. Action complètement différente.
```

## Pourquoi ne pas simplement utiliser les LLMs ?

« GPT/Claude ne peut pas juste mieux traduire ? »

Oui et non. Les LLMs *peuvent* produire de belles traductions. Mais ils ne savent pas :
- Qui est ce personnage (ses conflits, ses patterns de parole, ses tendances émotionnelles)
- À qui il parle (et ce que cette relation signifie)
- Dans quel état émotionnel il se trouve en ce moment
- Ce que cette réplique est censée *faire* à l'auditeur

Sans ce contexte, même le meilleur LLM va parfois :
- Transformer des déclarations en narration
- Aplatir la défense tsundere en simple dénégation
- Perdre le pattern « fuite émotionnelle puis correction » qui rend un personnage vivant

**La traduction Z-Axis donne aux LLMs le contexte dont ils ont besoin.**

## Comment ça marche

### 1. Ingénierie de Persona

Chaque personnage reçoit un **persona YAML** qui capture :
- **Axes de conflit** : « avouer ses sentiments vs. se protéger », « devoir vs. désir »
- **Patterns de biais** : comment les émotions émergent (ex: Tsun→Dere→Correction)
- **Déclencheurs** : ce qui les fait réagir (être appelé « assistante », être remercié)
- **Flags de risque** : où les traductions échouent typiquement pour ce personnage

### 2. Pipeline de Traduction (3 étapes)

```
ÉTAPE 1 : Extraction Hamiltonienne
          → Quels conflits sont actifs ? Quel est l'état émotionnel ?

ÉTAPE 2 : Analyse du Pattern d'Interférence
          → Comment ces conflits se manifestent dans le discours ?
          → Hésitation ? Dénégation ? Auto-correction ? Fuite émotionnelle ?

ÉTAPE 3 : Traduction avec Préservation Z-Axis
          → Générer un texte en langue cible qui performe la MÊME ACTION
```

### 3. Évaluation : IAP & ZAP

Nous avons construit deux évaluateurs pour mesurer ce qui compte :

| Métrique | Ce qu'elle mesure |
|----------|-------------------|
| **IAP** (Illocutionary Act Preservation) | La traduction performe-t-elle les mêmes actes de parole ? (déclarer, refuser, menacer...) |
| **ZAP** (Z-Axis Preservation) | Est-ce que ça sonne toujours comme le personnage ? L'intensité émotionnelle est-elle préservée ? |

## Résultats : Ce que nous avons trouvé

### Expérience 1 : La déclaration de Rem (Re:Zero)

| Système | Mode d'adresse | Score IAP | Ce qui s'est passé |
|---------|----------------|-----------|---------------------|
| DeepL | direct → **rapporté** | 0.51 | La déclaration est devenue narration |
| Z-Axis | direct → **direct** | 0.76 | Préservation de la déclaration face à face |

### Expérience 2 : Le tsundere de Kurisu (Steins;Gate)

Même réplique : 「別に...あんたのためじゃないから」

| Contexte | Sortie Z-Axis | Action |
|----------|---------------|--------|
| Quotidien | "C-c'est pas comme si c'était pour toi..." | Défense standard |
| Jalousie | "Je— enfin, c'est pas que je l'ai fait pour toi, hein ?" | Fuite émotionnelle → correction |
| Monologue | "C'est pas pour lui... enfin— c'est *pas* pour lui." | Auto-tromperie (double dénégation) |

**Les mêmes mots performent des actions différentes selon le contexte.**

### Expérience 3 : L'ultimatum de Luffy (One Piece)

« Si tu nous le dis, j'arrête d'être pirate. »

Test aller-retour EN→FR→EN. **L'ultimatum a survécu.** (Les actions explicites sont robustes.)

Mais le cadrage du refus compte :
- ❌ « Je m'en fiche où est le trésor » (apathie)
- ✅ « J'veux pas entendre où est le trésor » (poser une limite pour protéger le voyage)

Même sens. Voix du personnage différente.

## Démarrage Rapide

```bash
# Installation
pip install anthropic openai pyyaml python-dotenv requests

# Créer .env
ANTHROPIC_API_KEY=sk-ant-xxxxx   # Pour la génération de persona
OPENAI_API_KEY=sk-xxxxx          # Pour la traduction & évaluation

# Générer un persona
python persona_generator.py --name "レム" --source "Re:Zero" --desc "献身的メイド"

# Traduire avec préservation Z-axis
python z_axis_translate.py --config requests/rem_test.yaml

# Évaluer
python iap_evaluator.py -o "スバルくんが良いんです" -t "C'est toi que je veux, Subaru-kun"
python zap_evaluator.py --config requests/rem_test.yaml --translated "Je t'aime, Subaru-kun"
```

## Article

Ce dépôt accompagne notre rapport de pratique soumis au **Journal of Audiovisual Translation (JAT)** :

> **Translation as Action Preservation (TAP) : Évaluer la traduction anime/manga au-delà du sens**
>
> Nous proposons d'évaluer les traductions non seulement par la similarité sémantique, mais par leur capacité à préserver l'*action illocutoire*—ce que la réplique fait à l'auditeur et à la scène.

📄 [Lire l'article complet](#) *(lien à ajouter après publication)*

## Philosophie

> « Nous n'avons pas construit ça parce que les machines traduisent mal.
> Nous l'avons construit parce que **même les bonnes traductions peuvent tuer des personnages**. »

L'objectif n'est pas de remplacer les traducteurs. C'est d'externaliser une partie de la pratique experte : **garder l'action intacte à travers les langues**.

---

## License

MIT License — Use freely, preserve characters responsibly. 🌀

## Citation

If you use this work in research, please cite:

```bibtex
@article{tap2026,
  title={Translation as Action Preservation: Evaluating Anime/Manga Translation Beyond Meaning},
  author={[Author]},
  journal={Journal of Audiovisual Translation},
  year={2026},
  note={Practice Report}
}
```
