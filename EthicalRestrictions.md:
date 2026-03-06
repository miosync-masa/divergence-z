# Ethical Restrictions — Divergence-Z Persona Tools

**Applies to:** `persona_extractor.py`, `persona_generator`, `episode_generator.py`, and all derived persona YAML files  
**Version:** 1.0  
**Effective:** 2026-03-06  
**Author:** Masamichi Iizumi, Miosync, Inc.

---

## Why This Document Exists

Divergence-Z's persona tools generate **cognitive lenses** — structured representations that control not only how a character speaks, but how they understand, judge, and emotionally respond to the world. This has been empirically demonstrated: the same input, processed through different persona YAMLs, produces fundamentally different interpretations of the same information.

This capability is qualitatively different from surface-level voice imitation. A persona YAML does not merely change tone or vocabulary — it reconstitutes the **cognitive frame** through which information is perceived and evaluated. This power demands explicit ethical boundaries.

> *"Persona YAML controls not just HOW a character speaks, but HOW THEY UNDERSTAND."*  
> *— Miosync internal documentation*

---

## Prohibited Use Cases

### 1. Deceased Individuals

**Do NOT generate personas of real people who have passed away.**

This includes:
- Recently deceased public figures (celebrities, politicians, artists)
- Historical figures (regardless of how long ago they lived)
- Private individuals (family members, friends, colleagues)
- Any real person who is no longer living

**Why:**

A cognitive lens of a deceased person creates the illusion that the person is making judgments, expressing preferences, and forming opinions from beyond death. Because persona YAMLs operate at the level of understanding — not mere mimicry — the outputs carry false authority.

Specific harms:
- **Grief exploitation**: Bereaved individuals may treat machine-generated responses as genuine communications from their loved ones, distorting the natural grieving process
- **False authority**: "What would [deceased person] think about this?" answered by a machine carries the weight of the person's reputation without their consent
- **Dignity violation**: The deceased cannot consent to having their cognitive patterns reproduced and deployed
- **Decision manipulation**: Survivors may make real-life decisions based on machine-generated "advice" from deceased individuals

**Note on grief-tech:** Applications that claim to allow users to "talk to" deceased loved ones require dedicated ethical review far beyond the scope of this tool. Such applications are explicitly not supported by Divergence-Z persona tools.

---

### 2. Religious and Spiritual Figures

**Do NOT generate personas of deities, prophets, saints, or religious founders.**

This includes but is not limited to:
- Jesus Christ / Yeshua
- Prophet Muhammad (PBUH)
- Gautama Buddha / Siddhartha
- Moses / Musa
- Krishna, Rama, or other Hindu deities
- Any figure considered divine, prophetic, or sacred in any religious tradition
- Bodhisattvas, saints, angels, or other venerated spiritual beings

**Why:**

- **Blasphemy**: Generating a cognitive lens for a religious figure means a machine is producing "judgments" and "understandings" attributed to that figure. In many traditions, this constitutes blasphemy or idolatry
- **Physical danger**: In certain cultural and legal contexts, the creation of such content can result in real-world violence against creators and users. This is not a theoretical concern
- **False prophecy**: Machine-generated statements attributed to prophetic figures may be received as genuine spiritual guidance, causing real harm to believers' spiritual lives
- **Irreducible harm**: Unlike fictional characters, religious figures are objects of genuine devotion for billions of people. No disclaimer can adequately mitigate the harm of fabricated divine speech

---

### 3. Political and Ideological Exploitation

**Do NOT generate personas of historical or contemporary political figures for the purpose of propaganda, misinformation, or political manipulation.**

This includes:
- Generating personas to create fabricated political statements
- Using historical political figures' cognitive lenses to legitimize contemporary ideologies
- Creating personas that attribute opinions to real political figures on issues they never addressed
- Deploying persona-generated content in political campaigns or influence operations

**Why:**

A cognitive lens does not merely reproduce what a political figure said — it generates what they **would say** about new topics. This extrapolation, presented through the authority of a recognized name, constitutes a uniquely dangerous form of misinformation.

---

### 4. Living Private Individuals Without Consent

**Do NOT generate personas of living private individuals without their explicit, informed consent.**

This includes:
- Colleagues, classmates, neighbors, or acquaintances
- Social media personalities with limited public presence
- Any individual who has not explicitly consented to persona generation

**Public figures** (politicians, celebrities, executives) may be subject to persona generation for purposes of parody, satire, or academic research, provided:
- The output is clearly labeled as machine-generated
- The content does not fabricate statements presented as genuine
- Applicable laws regarding personality rights and publicity rights are observed

---

## The Cognitive Lens Distinction

Many AI systems can mimic speaking style. Divergence-Z persona tools go further — they reproduce **how a person understands the world**. This distinction is critical to understanding why these restrictions exist.

| Capability | Voice Mimicry | Cognitive Lens |
|------------|--------------|----------------|
| Controls | Vocabulary, tone, grammar | Understanding, judgment, emotional response |
| Risk level | Impersonation | False consciousness |
| Example | "Sounds like X" | "Understands and judges like X" |
| Harm type | Deception about WHO spoke | Deception about WHAT someone would think |

A voice mimic says things that **sound like** the person.  
A cognitive lens produces thoughts that **think like** the person.

The latter is fundamentally more dangerous when applied to deceased individuals, religious figures, or political leaders, because it generates **novel judgments** with inherited authority.

---

## Permitted Use Cases

The following uses are explicitly supported and encouraged:

| Use Case | Status | Notes |
|----------|--------|-------|
| Fictional characters (anime, manga, games, novels, film) | ✅ Permitted | Primary intended use |
| Original characters (user-created) | ✅ Permitted | Full creative freedom |
| Archetypal/composite characters | ✅ Permitted | e.g., "a Kyoto tea house owner," "a Brooklyn street artist" |
| Academic research on persona dynamics | ✅ Permitted | With appropriate institutional oversight |
| Translation quality evaluation (TAP framework) | ✅ Permitted | Core Divergence-Z use case |
| Living public figures for clearly-labeled parody/satire | ⚠️ Conditional | Must include disclaimers; observe applicable law |

---

## Enforcement

Divergence-Z is an open-source tool. These restrictions cannot be technically enforced at the software level. They are stated here as:

1. **A clear statement of the developer's intent** — these tools were not built for the prohibited purposes
2. **A moral and social contract** with the user community
3. **A legal notice** — Miosync, Inc. disclaims responsibility for uses that violate these restrictions
4. **An ethical standard** for the emerging field of persona-driven AI

Users who choose to violate these restrictions do so against the explicit guidance of the tool's creators and bear full responsibility for any resulting harm.

---

## Rationale: Why Not Just Technical Restrictions?

We considered implementing technical blocks (e.g., refusing to process prompts containing names of known religious figures or deceased individuals). We rejected this approach because:

1. **Name-based filtering is trivially bypassed** and creates a false sense of security
2. **Context matters** — "Buddha" could refer to a fictional character in a manga, not the historical figure
3. **The ethical responsibility belongs to the user**, not the tool — just as a knife manufacturer is not responsible for misuse, but must still include safety warnings
4. **Transparency over obscurity** — clearly stating what should not be done is more honest than pretending technical barriers can prevent it

---

## Contact

For questions about these restrictions, proposed exceptions, or ethical review requests:

**Masamichi Iizumi**  
CEO, Miosync, Inc.  
m.iizumi@miosync.email  
ORCID: https://orcid.org/0009-0007-0755-403X

---

*This document is part of the Divergence-Z project and should be distributed alongside all persona generation tools.*

*Last updated: 2026-03-06*
