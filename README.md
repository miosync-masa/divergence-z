# Divergence-Z 🌀

> 原作から「誰が・何を経験したか」の資料を作り、その資料で **翻訳** し、**声** にする。
> Build a character bible from the source text — then use it to **translate** and to **speak**.

🇯🇵 [日本語マニュアル](#日本語マニュアル) | 🇬🇧 [English manual](#english-manual)

```
原作テキスト ─┬─ CAST     人物表   誰がいて、本文でどう呼ばれているか
              ├─ PERSONA  ペルソナ  この人は誰か（話し方・核・葛藤）
              ├─ EPISODE  エピソード この人は何を経験したか（台詞は原文照合つき）
              │
              ├─▶ TRANSLATE  章ごとに資料＋訳語表＋前章を渡して翻訳
              │     └─▶ LOCALIZE  訳文はそのまま残し、宗教・性表現などをプリセットで調整した版を別に作る
              └─▶ VOICE      その人物の声で、原作にない台詞を言わせる
```

---

# 日本語マニュアル

## 目次

1. [これは何か](#1-これは何か)
2. [必要なもの](#2-必要なもの)
3. [インストール](#3-インストール)
4. [デスクトップアプリの使い方](#4-デスクトップアプリの使い方)
5. [コマンドライン（CLI）の使い方](#5-コマンドラインcliの使い方)
6. [モデルと費用](#6-モデルと費用)
7. [プロジェクトフォルダの中身](#7-プロジェクトフォルダの中身)
8. [プライバシーとセキュリティ](#8-プライバシーとセキュリティ)
9. [困ったとき](#9-困ったとき)
10. [開発者向け](#10-開発者向け)
11. [倫理的な制約・旧版・論文・ライセンス](#11-倫理的な制約旧版論文ライセンス)

## 1. これは何か

小説・脚本・ゲームのテキストを丸ごと LLM に読ませて、登場人物の「設定資料」を作るツールです。
脚本家や翻訳者が手作業で作っている人物資料を自動化し、その資料をそのまま次の用途に使います。

| 作るもの | 中身 |
|---|---|
| **人物表（cast）** | 登場人物の一覧と、本文での呼ばれ方（「彼女」「搭乗者」「宇宙から来た少女」など）。名前が出てこない作品でも、誰の台詞かを判定できるようにする |
| **ペルソナ（persona）** | その人物は誰か。一人称・語尾・口癖、核となる性格、葛藤、感情で話し方がどう崩れるか、他言語での補償方法 |
| **エピソード（episode）** | その人物が何を経験したか。章ごとの出来事・感情の変化・原作の台詞。台詞は原文と照合して実在を確認する |

| 使い道 | 中身 |
|---|---|
| **翻訳** | 1章ずつ、原文＋その章の登場人物の資料＋訳語表＋直前の訳文を渡して訳す。訳語や人物の声の決定は訳語表に溜まり、次の章に引き継がれる |
| **ボイス** | 資料をもとに、原作にない台詞をその人物の声で言わせる。2人の掛け合いもできる |

### 一般的な翻訳 API との違い

一般的な翻訳 API にも、文脈を伝える仕組みはあります。ただし、**その中身はすべて人間が作って登録するもの**です。
Divergence-Z は、翻訳に必要な人物の特性を**原作そのものから抽出**します。人間が指示を書く必要はありません（出来上がった資料は確認・修正できます）。

| 制御するもの | 一般的な翻訳 API（人間が用意する） | Divergence-Z（原作から作る） |
|---|---|---|
| 用語の訳 | 用語集を手で登録する | **訳語表**：章を訳すたびに自動で追記され、次の章へ引き継がれる |
| 書式・表記 | 書式のスタイル規則を手で設定する | 訳語表の **style**：括弧・数字・見出しの扱いを訳しながら決めて記録する |
| トーン・口調 | 自然言語のカスタム指示を人間が書く（作品全体で1つ） | **ペルソナ**：人物ごとに、一人称・語尾・口癖・感情で話し方がどう崩れるかを原作から抽出 |
| 以前の訳の再利用 | 翻訳メモリ（一致する文の訳を再利用） | 直前の訳文と訳語表を毎回渡す。一致する文ではなく、決定を引き継ぐ |
| 誰の台詞か | 扱わない | **人物表**：名前の出ない作品でも、「彼女」「搭乗者」が誰かを判定する |
| 何を経験したか | 扱わない | **エピソード**：この章より前／この章／この先 を分けて渡す（先の出来事は漏らさない） |

文単位の翻訳 API が悪いわけではなく、**用途が違います**。文書・メール・技術文書では、1文ずつ自然で標準的な訳を速く安く返すことが正解です。
小説やエンタメで価値があるのは、1文の正しさよりも **本1冊を通した決定**（誰がどう話すか、何を繰り返すか、作者のどの癖を残すか）です。

作例：이상『날개（翼）』のプロローグ（全文は `Result/Korea/`）

| | 原文 | 文単位の翻訳 API | Divergence-Z |
|---|---|---|---|
| 意味 | 정신**분일**자（奔逸） | 精神**分裂**者 | 精神奔逸者 |
| 意味 | **횟배** 앓는 뱃속 | 胃痛に悩まされる腹 | **回虫に**病む私の腹 |
| 固有名 | **위고**를 불란서의 빵… | **ヴィゴ**を「フランスのパン一片」 | **ユゴー**を仏蘭西のパン一切れ |
| 声 | 하오체（〜오）で一貫 | です体 と だ体 が段落内で混在 | です／ます で一貫。終盤の 합네다 のずれは「〜のであります」で出す |
| 反復 | 굿바이 を繰り返す | 「グッバイ」の次が「さようなら」 | グッドバイ で通す（訳語表で決定） |
| 作者の仕掛け | 영수(받아들이는) のような括弧の言い換え | 漢語を落として言い換えだけ残す箇所がある | 領収（受け入れる）。括弧書きを残す方針を訳語表に記録 |

**BYOK（Bring Your Own Key）**：API キーは自分のものを使います。原稿もキーもあなたの PC から外には出ません（送信先は OpenAI / Anthropic の API だけ）。

## 2. 必要なもの

- macOS（Apple シリコンで動作確認）。Windows / Linux はコード上は対応していますが未検証です
- Python 3.10 以上
- Node.js 20 以上（デスクトップアプリを使う場合）
- API キー（どちらか、または両方）
  - **OpenAI**：抽出と翻訳の既定モデル `gpt-5.6-sol`
  - **Anthropic**：Web 検索での生成とボイスの既定モデル `claude-opus-5-5`

  使うモデルはステップごとに変えられます（[6. モデルと費用](#6-モデルと費用)）。

## 3. インストール

### アプリだけ使う（Mac・Apple シリコン）

[Releases](https://github.com/miosync-masa/divergence-z/releases) から `Divergence-Z-<version>-arm64.dmg` をダウンロードして、アプリをアプリケーションフォルダに入れます。Python も Node も不要です。

このビルドは Apple の署名・公証をしていないため、初回は Finder でアプリを右クリック →「開く」で起動してください（開けない場合は システム設定 → プライバシーとセキュリティ →「このまま開く」）。

### ソースから使う（CLI・開発）

```bash
git clone https://github.com/miosync-masa/divergence-z.git
cd divergence-z

# Python 側（エンジン）
python3 -m venv .venv
.venv/bin/pip install -e ".[server]"

# デスクトップアプリ
cd app
npm install
npm run build
npm start
```

起動すると左下に `● ENGINE` と出れば準備完了です。2回目以降は `cd app && npm start` だけで起動できます。

CLI だけ使う場合は、デスクトップアプリの手順は不要です。リポジトリ直下に `.env` を作ってキーを書きます（`.env.example` をコピー）。

## 4. デスクトップアプリの使い方

### 4.1 API キーを設定する

左のメニュー「**キー & モデル**」で OpenAI / Anthropic のキーを入れて保存します。
キーは OS のキーチェーンで暗号化して保存され、画面に読み戻されることはありません。
同じ画面の「モデル登録表」で、各モデルのコンテキスト長・推論の強さ・料金を確認できます。

### 4.2 プロジェクトを作る

作品1つ＝プロジェクト1つ＝フォルダ1つです。

- **＋ 新しいプロジェクト**
  1. 資料と訳文の**保存先**フォルダ（空のフォルダ推奨）を選ぶ
  2. **原稿フォルダ**を選ぶ。章ごとに分かれたテキスト（`.txt` `.md`）、PDF、EPUB に対応。フォルダ内のファイルは名前の数字順（`ep2 < ep10`）に読まれます
  3. プロジェクト名・作品名・資料の説明文の言語を入れて「作成して開く」
- **既存のプロジェクトを開く**
  以前のプロジェクトや、CLI で `casts/` `personas/` `episodes/` を作ったフォルダを登録します。原稿フォルダが未設定なら、開いたあと「設定」タブで指定してください。

### 4.3 パイプライン（一気通貫で実行）

「**パイプライン**」タブが基本の画面です。

1. 上の4枚のカード（01 人物表 / 02 ペルソナ / 03 エピソード / 04 翻訳）で進み具合が分かります。カードの「このステップだけ実行」で個別にも動かせます
2. 「**対象キャラクター**」で資料を作る人物を選びます。未選択なら人物表で `main ★` の人物が対象です（端役は「+ 端役 N人」で表示）
3. 「**翻訳先の言語**」を選びます（複数可）
4. 「**$ 見積もる**」で、API を呼ばずにステップごとのトークン数・モデルに収まるか・概算費用を確認します
5. 「**▶ パイプライン実行**」で、人物表 → ペルソナ → エピソード → 翻訳 の順に実行します
6. 人物表ができると、いったん止まって **確認待ち**（黄色のバナー）になります。「人物表を開く」で内容を確認・修正し、「**OK、続ける ▶**」で再開します（確認を挟まない設定も可）

実行中は下のジョブコンソールに進行状況とトークン使用量が流れます。「■ 中止」で止められ、受信中のリクエストもすぐに切ります。
**作成済みの資料・訳済みの章は自動でスキップ**するので、中止や失敗のあとは同じ操作をもう一度するだけで続きから再開します。

### 4.4 人物表を確認・修正する

「**人物表**」タブで、人物ごとに次を確認します。

- **ラベル**：ペルソナ / エピソードのファイル名と、翻訳時の呼び名になります。固有名が無い作品では「宇宙から来た少女」のような記述がラベルになるので、好みの呼び方に直してから先に進むのがおすすめです
- **重要度**：`main ★` の人物が既定で資料作成の対象になります
- **呼ばれ方（REFERENCES）**：本文でその人物を指す表現。行をクリックすると、同一人物と判定した根拠や、同じ「彼女」が別人を指す箇所の見分け方が見られます

表で直して「保存」。細かい修正は「YAML を直接編集」でもできます。

> ラベルを変えたあとにペルソナ / エピソードを作り直したい場合は、古いファイルを消してからパイプラインを再実行してください（既存のファイルはスキップされるため）。

### 4.5 翻訳を確認する

「**翻訳**」タブ：

- 左：言語の切り替えと章の一覧（`DONE` / `PENDING` / `INCOMPLETE`）
- 右：原文と訳文を段落番号つきで並べた対訳。「この章を再翻訳」で1章だけ訳し直せます
- 「**訳語表**」：これまでに決まった訳語（例：当機 → this unit）と、人物の声の決め方（例：少女の片言をどう訳すか）。章を訳すたびに追記され、次の章に引き継がれます

段落の抜けがあった章は `INCOMPLETE` になります。もう一度翻訳を実行すれば訳し直します。

### 4.6 ローカライズ（宗教・性表現などの調整）

「**ローカライズ**」タブ。訳し上がった訳文（L0）には一切触らず、調整した版を `translations/<言語>@<版の名前>/` に別に作ります。

1. 「宗教・性表現などを調整しますか？」でプリセットを選ぶ（複数可。後から選んだものが優先）
2. 必要なら「領域ごとに微調整」で、領域ごとの処理を変える
3. 実行すると、章ごとに **変更一覧** ができる。気に入らない変更は「↩ 戻す」で1件ずつ戻せる（API は呼びません）

| プリセット | すること |
|---|---|
| 読者配慮（訳注のみ） | 文化固有の語に短い補足を足す。置き換えはしない |
| 市場適応（等価置換） | 商品・生活文化と表記（度量衡・通貨・日付）を読者の文化の等価物に |
| PG15（性・暴力表現の緩和） | 露骨な描写の**修飾部**（擬態語・程度表現）だけを抑える。出来事と述語は変えない |
| ハラール配慮（豚肉・飲酒） | 筋に関わらない豚肉・飲酒を等価物に。筋に関わるものは診断のみ |
| 宗教的冒涜表現の調整 | 神名を使った罵倒などを、同じ強さの世俗的な言い回しに |
| 市場診断のみ | 本文には触れず、摩擦しうる箇所だけを報告 |

処理の種類：**補完**（L2・訳注を足す）／**等価置換**（L3・強度と機能は保つ。表記は L1）／**緩和**（強度を下げる。利用者が選んだときだけ）／**診断のみ**（L4・本文に触れない）。

ツールが勝手に変えないための仕組み：

- LLM は本文を書き直さず、「修正リスト」と「診断」だけを返す。置換前の文字列がその段落の L0 にちょうど1回出てくるときだけ適用する
- 方針外の修正・他の修正と重なる修正・修飾部を越えて述語に手を入れた緩和（日本語・韓国語）・訳語表で決めた語を消す緩和は、理由つきで「適用せず」として台帳に残る
- 出力は、クリーン版（`.md`、納品物）・注記版（`.annotated.md`、変更箇所に `〔L3・商品: 元の訳〕` の標識）・台帳（`.ledger.json`）・診断（`.diagnosis.md`）

作品ごとのプリセットは `localize/presets/*.yaml` に置くと一覧に出ます（同梱分と同じ id なら上書き）。作例：`Result/Korea/`（이상『날개』の `ja@pg15`）。

### 4.7 ボイス

「**ボイス**」タブで、ペルソナがある人物に、原作にない台詞を言わせられます。

- **話す人**・**言わせたいこと**・**状況** を入れて「▶ 声にする」
- **聞き手**を選ぶと相手を意識した言い方になり、「デュアル」にすると聞き手が返事をします
- **出力言語**を選ぶと、その人物らしさを保ったまま他の言語で出力します
- 「分析を見る」で、適用された感情の状態（z_mode）や揺れの表れ方（z_leak）を確認できます

### 4.8 Web 生成（原作テキストが無いとき）

「**Web 生成**」タブでは、キャラクター名と作品名だけで、Web 検索をもとにペルソナとエピソードを作れます
（`persona_generator.py` → `episode_generator.py`）。原作テキストがある作品は、パイプラインの抽出の方が正確です。

- **キャラクター名**は、人物表のラベルと同じにすると翻訳でこの資料が使われます（入力欄に候補が出ます）
- **モデル**は Web 検索に対応したものだけが選べます（現在は Anthropic のモデル）
- エピソードは、直前に作ったペルソナを参考にして作ります。作成済みの資料は「既存を作り直す」を付けない限りスキップします
- 「Web 検索する」を外すとモデルの知識だけで作ります。台詞が実在しないものになりやすいので注意してください

### 4.9 AIチャット

左メニューの「**AIチャット**」で、ペルソナを作った人物と会話できます。

- 「＋ 新しい会話」で、プロジェクト・話す相手・モデル・推論の強さ・「あなたについて」（関係性など、任意）を選んで始めます
- システム指示は「**共通システム指示**」（全会話で共通のテンプレート）に、その人物のペルソナとエピソードを**省略せず丸ごと**差し込んだものです。右上の「共通システム指示を編集」で変更できます
  - `{{CHARACTER}}` → 人物名、`{{PERSONA_EPISODE}}` → ペルソナとエピソードの YAML、`{{USER}}`（任意）→「あなたについて」
  - テンプレートは `~/.divergence_z/chat_template.md` に保存されます（リポジトリには入りません）
- システム指示が長い（数万トークン）ため、Anthropic のモデルではプロンプトキャッシュを使います。2回目以降の発言では、その部分が約1/10の料金になります
- 会話ログはプロジェクトフォルダの `chats/` に保存され、手元の PC から出ません
- 指示の内容によっては、モデルの安全機能に断られることがあります（`ERR::refusal`）

### 4.10 設定

「**設定**」タブで、プロジェクト名・原稿フォルダ・資料の説明文の言語と、**ステップごとのモデルと推論の強さ**を変えられます。
たとえば「抽出は大きいモデル + max、試し訳は安いモデル + low」のように使い分けられます。

## 5. コマンドライン（CLI）の使い方

アプリと同じ処理をコマンドでも実行できます。リポジトリ直下に `.env`（`.env.example` を参照）を置き、`divergence_z/` で実行します。

```bash
cd divergence_z
PY=../.venv/bin/python
```

### 原作テキストがある場合

```bash
# 1. 人物表 → casts/STARGAZER_cast.yaml（中身を確認・修正してから次へ）
$PY cast_extractor.py -s ../path/to/STARGAZER/ --work "STARGAZER ≠consciousness"

# 2. ペルソナ → personas/{ラベル}_extracted_v33.yaml
$PY persona_extractor_v2.py -s ../path/to/STARGAZER/ --cast casts/STARGAZER_cast.yaml \
  --characters "宇宙から来た少女,主人公" --lang ja

# 3. エピソード → episodes/{ラベル}_Episode.yaml（台詞の原文照合結果も表示）
$PY episode_extractor.py -s ../path/to/STARGAZER/ --cast casts/STARGAZER_cast.yaml \
  --characters "宇宙から来た少女,主人公" --work "STARGAZER ≠consciousness"

# 4. 翻訳 → translations/STARGAZER_en/
$PY chapter_translator.py -s ../path/to/STARGAZER/ --cast casts/STARGAZER_cast.yaml \
  -t en --chapters 0-2          # 0〜2章目。省略すると全章
$PY chapter_translator.py ... --dry-run   # API を呼ばずにトークン数・費用だけ表示
```

長い章（既定 6,000 字超、`--max-section-chars` で変更）は、まず LLM が場面の切れ目でセクションに分ける計画を立て、
セクションごとに1回ずつ訳します。各セクションには章の計画・直前の訳文・そのセクションの登場人物の資料だけを渡します。
途中で止まっても、再実行すれば終わったセクションの続きから再開します。

名前で呼ばれる作品なら `--cast` は省略できます。`--source` には単一ファイル（txt / md / pdf / epub）も指定できます。

### ローカライズ

```bash
$PY localizer.py --list-presets
# 訳し上がった章（translations/STARGAZER_en/）を PG15 で → translations/en@pg15/
$PY localizer.py -i translations/STARGAZER_en -t en -p pg15
$PY localizer.py ... -p market_adapt -p pg15 --set violence=keep   # 重ねがけ・領域ごとの上書き
$PY localizer.py ... -p pg15 --revert stargazer_ep01:E003          # 1件戻す（API を呼ばない）
```

### 原作テキストが無い場合（Web 検索で生成）

```bash
$PY persona_generator.py --name "牧瀬紅莉栖" --source "Steins;Gate" --desc "天才脳科学者"
$PY episode_generator.py --name "牧瀬紅莉栖" --source "Steins;Gate" --desc "天才脳科学者" \
  --persona personas/牧瀬紅莉栖_v33.yaml
```

### ボイス

```bash
$PY persona_voice.py --persona "personas/宇宙から来た少女_extracted_v33.yaml" \
  --episode "episodes/宇宙から来た少女_Episode.yaml" \
  --input "今日の夕飯はカレーにしよう" --context "主人公の家の台所"

# 2人の掛け合い
$PY persona_voice.py --persona A.yaml --target-persona B.yaml --dual --input "..." --context "..."
```

### 共通オプション

| オプション | 説明 |
|---|---|
| `--model` / `-m` | 使うモデル（登録表の id。登録表に無い名前でも可） |
| `--effort` | 推論の強さ `none/low/medium/high/xhigh/max`（モデルにより使える値が違う） |
| `--lang` | 資料の説明文の言語（台詞・話し方は原文の言語のまま） |
| `--help` | すべてのオプション |

旧オプション `--thinking N` / `--budget N` / `--reasoning` は互換のため残っています（`--thinking` / `--budget` は `--effort high` 扱い）。

## 6. モデルと費用

### モデル登録表

アプリと CLI は同じ登録表を使います。組み込みのモデル：

| モデル | 用途の既定 | コンテキスト | 料金（入力 / 出力, 1M トークン） |
|---|---|---|---|
| `gpt-5.6-sol` | 人物表・ペルソナ・エピソード・翻訳 | 未設定（契約による） | 未設定 |
| `claude-opus-5-5` | ボイス・Web 生成 | 1,000,000 | $4 / $20 |
| `claude-sonnet-5-5` | — | 1,000,000 | $2 / $10 |
| `claude-fable-5-1` | — | 1,000,000 | $10 / $50 |
| `claude-opus-4-5-20251101` | 旧既定 | 200,000 | $5 / $25 |
| `claude-haiku-4-5` | — | 200,000 | $1 / $5 |

モデルを追加したり値を直したりするには `divergence_z/models.example.yaml` を `~/.divergence_z/models.yaml` にコピーして編集します。
**`gpt-5.6-sol` などコンテキスト長が未設定のモデルは、ここに値を入れると見積もりで「収まるか」を判定できるようになります。**

### どれくらいかかるか

見積もりは日本語 1 文字 ≒ 1.4 トークンで計算します。参考（約12万字・26章の小説）：

- 人物表・ペルソナ・エピソードは、毎回原作全文（約14万トークン）を入力します
- 翻訳は1章あたり入力 7〜8万トークン（原文＋資料＋訳語表＋前章）。Claude Opus 5.5 で1章約 $0.5

実行前に必ず「$ 見積もる」（CLI は `--dry-run`）で確認してください。

## 7. プロジェクトフォルダの中身

```
MyProject/
  project.yaml            プロジェクト設定（名前・原稿のパス・言語・ステップごとのモデル）
  casts/cast.yaml         人物表
  personas/               ペルソナ YAML
  episodes/               エピソード YAML
  translations/<言語>/
    <章>.<言語>.md              訳文
    <章>.<言語>.segments.json   原文と訳文の段落対応
    translation_notes.yaml      訳語表（手で直してよい）
  translations/<言語>@<版>/     ローカライズ版（L0 は変えない）
    <章>.<言語>.md / .annotated.md / .ledger.json / .diagnosis.md、policy.yaml
  localize/presets/       作品ごとのローカライズ・プリセット
  .dz/jobs/               ジョブの履歴（API キーは含まない）
```

すべて普通の YAML / Markdown です。エディタで直接直しても、アプリはそれを読み込みます。

## 8. プライバシーとセキュリティ

- API キーは OS のキーチェーン（macOS ではキーチェーン）で暗号化して保存。アプリの画面側には渡りません
- エンジン（Python）は自分の PC の中（127.0.0.1）だけで動き、起動ごとに作るトークンが無い接続は拒否します
- 原稿・資料・訳文はプロジェクトフォルダにだけ保存されます。外部に送るのは、各ステップで LLM に渡す内容（原稿や資料）を、あなたのキーで契約している OpenAI / Anthropic に送る分だけです
- 他人の作品を扱う場合は、権利者の許諾の範囲で使ってください

## 9. 困ったとき

| 症状 | 対処 |
|---|---|
| 左下が `ENGINE DOWN` | `~/Library/Application Support/divergence-z-app/sidecar.log` を確認。`.venv` が無い / 依存が入っていない場合は [3. インストール](#3-インストール) をやり直す。別の Python を使うなら環境変数 `DZ_PYTHON` で指定 |
| `ERR::auth_missing` | そのモデルのプロバイダのキーが未設定。「キー & モデル」で設定 |
| `ERR::auth_invalid` | キーが無効、またはそのモデルを使う権限が無い |
| `ERR::context_too_large` | 原稿＋資料がモデルに収まらない。コンテキストの大きいモデルに変更 |
| `ERR::rate_limited` | 少し待ってから同じ操作を再実行（続きから再開します） |
| `ERR::refusal` | モデルがリクエストを断った。内容を確認するか別のモデルで試す |
| 章が `INCOMPLETE` | 段落の抜けを検出。再翻訳すれば訳し直します |
| `*_BROKEN.yaml` ができた | LLM の出力が YAML として壊れていた。手で直してリネームするか、再実行 |
| ラベルを直したのに資料が古い名前のまま | 既存ファイルはスキップされるので、古いファイルを消してから再実行 |
| 人物表や訳文が読み込まれない | 「原稿フォルダ」にプロジェクトのフォルダを指定していないか確認。原稿フォルダは原稿だけを読みます。`project.yaml` のあるフォルダは、一覧の「フォルダを開く」でプロジェクトとして開く（指定するとアプリが確認を出します） |

## 10. 開発者向け

```
app/                     デスクトップアプリ（Electron + React）        → app/README.md
divergence_z/
  core/                  LLM 呼び出し（BYOK）・モデル登録表・読み込み・YAML 処理
  server/                ローカル API（FastAPI、ジョブ・SSE）           → divergence_z/server/README.md
  cast_extractor.py      人物表
  persona_extractor_v2.py / persona_generator.py   ペルソナ（原文から / Web 検索で）
  episode_extractor.py / episode_generator.py      エピソード（原文から / Web 検索で）
  chapter_translator.py  章単位の翻訳
  persona_voice.py       ボイス
  old/                   旧 Z軸翻訳系（アーカイブ）
```

各スクリプトはライブラリ関数としても使えます（詳細は `divergence_z/README.md`）。

```python
from divergence_z.core import LLM, Keys, load_source_corpus
from divergence_z.persona_extractor_v2 import extract_persona

corpus, _ = load_source_corpus("path/to/STARGAZER/")
result = extract_persona(corpus, "宇宙から来た少女", llm=LLM(Keys(openai="sk-...")),
                         effort="high", output_lang="ja")
print(result.valid, result.yaml_text)
```

## 11. 倫理的な制約・旧版・論文・ライセンス

- **倫理的な制約**：ペルソナは話し方だけでなく「物事の受け取り方」まで再現します。実在の故人のペルソナ作成などは禁止しています。使う前に必ず [EthicalRestrictions.md](EthicalRestrictions.md) を読んでください
- **旧版**：行ごとに Z軸状態を推定して訳し、IAP / ZAP で採点していた旧系統は `divergence_z/old/` にあります（[old/README.md](divergence_z/old/README.md)）。`Result/` の実験結果はこの旧系統によるものです
- **論文**：旧系統の実践報告を *Journal of Audiovisual Translation (JAT)* に投稿しています — *Translation as Action Preservation (TAP): Evaluating Anime/Manga Translation Beyond Meaning*
- **ライセンス**：MIT License

```bibtex
@article{tap2026,
  title={Translation as Action Preservation: Evaluating Anime/Manga Translation Beyond Meaning},
  author={[anonymous]},
  journal={Journal of Audiovisual Translation},
  year={2026},
  note={Practice Report}
}
```

---

# English manual

## Contents

1. [What it is](#1-what-it-is)
2. [Requirements](#2-requirements)
3. [Install](#3-install)
4. [Using the desktop app](#4-using-the-desktop-app)
5. [Using the CLI](#5-using-the-cli)
6. [Models and cost](#6-models-and-cost)
7. [Project folder layout](#7-project-folder-layout)
8. [Privacy and security](#8-privacy-and-security)
9. [Troubleshooting](#9-troubleshooting)
10. [For developers](#10-for-developers)
11. [Ethics, legacy system, paper, license](#11-ethics-legacy-system-paper-license)

## 1. What it is

Divergence-Z has an LLM read an entire novel, script, or game text and build a **character bible** — the kind of reference material scriptwriters and translators make by hand — and then uses that bible directly.

| Builds | Contents |
|---|---|
| **Cast sheet** | Every character and every way the text refers to them ("she", "the passenger", "the girl who came from space"…), so lines can be attributed even in works that never name their characters |
| **Persona** | Who the character is: pronouns, sentence endings, verbal tics, core identity, conflicts, how their speech breaks under emotion, and compensation strategies for other languages |
| **Episodes** | What the character lived through, chapter by chapter, with canonical quotes **verified against the source text** |

| Uses | Contents |
|---|---|
| **Translation** | One chapter at a time, with the chapter's characters' bible, a running glossary, and the previous translated chapters. Decisions about terms and each character's voice are recorded in the glossary and carried forward |
| **Voice** | Make a character say new, non-canonical lines in their own voice — including two-character exchanges |

### How it differs from a general translation API

General translation APIs do have ways to pass context — but **a human has to write and register all of it**.
Divergence-Z **extracts the character traits a translation needs from the source itself**. Nobody has to write instructions (you can still review and edit the generated bible).

| Controls | General translation API (prepared by a human) | Divergence-Z (built from the source) |
|---|---|---|
| Term translations | A glossary you register by hand | **Glossary notes**: appended automatically after every chapter and carried forward |
| Formatting | Formatting style rules you configure | **style** notes: brackets, numerals, headings decided and recorded while translating |
| Tone and register | Natural-language custom instructions a human writes (one for the whole work) | **Persona**: per character — pronouns, sentence endings, verbal tics, how speech breaks under emotion — extracted from the text |
| Reusing past translations | Translation memory (reuses matching sentences) | The previous translation and the glossary are passed every time: decisions carry forward, not just matching sentences |
| Who is speaking | Not handled | **Cast sheet**: resolves "she" or "the passenger" even in works where no one is named |
| What the character has lived through | Not handled | **Episodes**: split into before / this chapter / not yet (future events are not leaked) |

Sentence-level translation APIs are not worse — **they serve a different purpose**. For documents, email, and technical text, a fast, cheap, natural translation of each sentence is exactly right.
In fiction and entertainment, what matters is less the correctness of each sentence than **the decisions that hold across a whole book**: who speaks how, what recurs, which of the author's habits survive.

Example: the prologue of Yi Sang's *Wings* (날개), Korean → Japanese (full text in `Result/Korea/`)

| | Source | Sentence-level translation API | Divergence-Z |
|---|---|---|---|
| Meaning | 정신**분일**자 ("a mind that wanders freely") | 精神**分裂**者 ("schizophrenic") | 精神奔逸者 |
| Meaning | **횟배** 앓는 뱃속 (a belly sick with roundworms) | 胃痛 ("stomach ache") | **回虫** (roundworms) |
| Names | **위고** (Hugo) | ヴィゴ ("Vigo") | ユゴー (Hugo) |
| Voice | One archaic register (하오체) throughout | Polite and plain forms mixed within a paragraph | One polite register; the late shift to 합네다 rendered as 〜のであります |
| Refrain | 굿바이 repeated | グッバイ, then さようなら | グッドバイ every time (fixed in the glossary) |
| Author's device | Parenthetical glosses like 영수(받아들이는) | Sometimes drops the term and keeps only the gloss | 領収（受け入れる）— the policy to keep them is recorded in the glossary |

**BYOK (Bring Your Own Key):** you use your own API keys. Neither your manuscript nor your keys leave your machine, except for the requests sent to OpenAI / Anthropic under your own account.

## 2. Requirements

- macOS (tested on Apple silicon). Windows / Linux are supported in code but untested
- Python 3.10+
- Node.js 20+ (for the desktop app)
- API keys (one or both)
  - **OpenAI** — default model for extraction and translation: `gpt-5.6-sol`
  - **Anthropic** — default model for web-search generation and voice: `claude-opus-5-5`

  The model can be changed per step ([6. Models and cost](#6-models-and-cost)).

## 3. Install

### App only (Mac, Apple silicon)

Download `Divergence-Z-<version>-arm64.dmg` from [Releases](https://github.com/miosync-masa/divergence-z/releases) and drag the app to Applications. No Python or Node needed.

The build is not signed or notarized by Apple: on first launch, right-click the app in Finder → Open (or allow it in System Settings → Privacy & Security).

### From source (CLI, development)

```bash
git clone https://github.com/miosync-masa/divergence-z.git
cd divergence-z

# Engine (Python)
python3 -m venv .venv
.venv/bin/pip install -e ".[server]"

# Desktop app
cd app
npm install
npm run build
npm start
```

When `● ENGINE` appears at the bottom left, you're ready. Afterwards, `cd app && npm start` is enough.

For CLI-only use, skip the app and put your keys in `.env` at the repo root (copy `.env.example`).

## 4. Using the desktop app

### 4.1 Set your API keys

Open **キー & モデル (Keys & Models)** in the sidebar, enter your OpenAI and/or Anthropic key, and save.
Keys are encrypted with the OS keychain and are never sent back to the UI.
The model registry on the same screen shows each model's context window, effort levels, and pricing.

### 4.2 Create a project

One work = one project = one folder.

- **＋ 新しいプロジェクト (New project)**
  1. Pick the folder where the bible and translations will be **saved** (an empty folder is best)
  2. Pick the **manuscript folder** — per-chapter text files (`.txt`, `.md`), PDF, or EPUB. Files are read in natural order (`ep2 < ep10`)
  3. Enter the project name, work title, and the language for descriptions, then create
- **既存のプロジェクトを開く (Open existing project)**
  Registers a previous project, or a folder where you created `casts/`, `personas/`, `episodes/` with the CLI. If no manuscript folder is set, set it in the Settings tab.

### 4.3 Pipeline (run everything)

The **パイプライン (Pipeline)** tab is the main screen.

1. The four cards (01 Cast / 02 Persona / 03 Episode / 04 Translate) show progress. "このステップだけ実行" runs a single step
2. Choose **target characters**. If none are chosen, characters marked `main ★` in the cast sheet are used (minor characters are behind "+ 端役 N人")
3. Choose **target languages** (multiple allowed)
4. **$ 見積もる (Estimate)** shows tokens, context fit, and cost per step — without calling any API
5. **▶ パイプライン実行 (Run)** runs cast → persona → episode → translation
6. When the cast sheet is ready the job pauses for **review** (yellow banner). Check it in the Cast tab, then press **OK、続ける ▶** to resume (review can be turned off)

The job console streams progress and token usage. **■ 中止 (Cancel)** stops immediately, even mid-request.
**Existing bible files and translated chapters are skipped**, so after a cancel or failure, just run again to continue.

### 4.4 Review the cast sheet

In the **人物表 (Cast)** tab, check each character:

- **Label** — used for persona / episode file names and as the character's name during translation. In works without proper names the label is a description (e.g. "宇宙から来た少女"), so rename it to what you want before continuing
- **Importance** — `main ★` characters are the default targets
- **References** — every expression the text uses for this person. Click a row to see why the model judged two references to be the same person, and how to tell apart a pronoun that refers to different people

Save after editing, or use "YAML を直接編集" for raw edits.

> To rebuild a persona / episode after renaming a label, delete the old file first (existing files are skipped).

### 4.5 Review translations

The **翻訳 (Translate)** tab:

- Left: language and chapter list (`DONE` / `PENDING` / `INCOMPLETE`)
- Right: source and translation side by side, paragraph by paragraph. "この章を再翻訳" re-translates one chapter
- **訳語表 (Glossary)**: decided terms (e.g. 当機 → *this unit*) and voice decisions (e.g. how the girl's broken Japanese is rendered). Updated after every chapter and passed to the next

Chapters with missing paragraphs are marked `INCOMPLETE`; translate again to fix them.

### 4.6 Localize (religion, sexual content, and more)

The **ローカライズ (Localize)** tab. The finished translation (L0) is never touched; each adjusted version is written to `translations/<lang>@<variant>/`.

1. Under "宗教・性表現などを調整しますか？" pick one or more presets (later picks win)
2. Optionally tweak the action per domain
3. Run it. Each chapter gets an **edit list**; revert any single edit with "↩ 戻す" (no API call)

| Preset | What it does |
|---|---|
| reader_notes | Adds short glosses to culture-specific terms; never replaces them |
| market_adapt | Replaces products, everyday items, and notation (units, currency, dates) with equivalents for the reader |
| pg15 | Tones down only the **modifiers** (mimetic words, degree phrases) of explicit sex and violence; events and predicates stay |
| halal | Swaps incidental pork and alcohol for equivalents; plot-relevant ones are only diagnosed |
| religious_profanity | Turns oaths using the sacred into secular ones of the same strength |
| diagnose_only | Touches nothing; reports passages that may conflict |

Actions: **annotate** (L2, add a gloss) / **substitute** (L3, keep intensity and function; L1 for notation) / **soften** (lower intensity, only when you choose it) / **flag** (L4, diagnosis only).

How it avoids silent changes:

- The model never rewrites text. It returns an edit list and diagnoses, and an edit is applied only when its "before" occurs exactly once in the L0 paragraph
- Out-of-policy edits, overlapping edits, softening that reaches past the modifiers into the predicate (Japanese/Korean), and softening that removes a glossary term are kept in the ledger as rejected, with a reason
- Output: clean text (`.md`, the deliverable), annotated text (`.annotated.md`, with markers like `〔L3・商品: original〕`), ledger (`.ledger.json`), diagnoses (`.diagnosis.md`)

Project-specific presets go in `localize/presets/*.yaml` (same id overrides a built-in). Example: `Result/Korea/` (Yi Sang's *Wings*, `ja@pg15`).

### 4.7 Voice

In the **ボイス (Voice)** tab, characters with a persona can say new lines:

- Enter **speaker**, **what to say**, and **situation**, then "▶ 声にする"
- Pick a **listener** to address someone; enable **dual** to have the listener reply
- Pick an **output language** to keep the character's voice in another language
- "分析を見る" shows the emotional state (z_mode) and how it leaks into speech (z_leak)

### 4.8 Web generation (no source text)

The **Web 生成 (Web generation)** tab builds a persona and episodes from just a character name and a work title,
using web search (`persona_generator.py` → `episode_generator.py`). With source text, pipeline extraction is more accurate.

- Use the cast-sheet label as the **character name** so translation picks these files up (labels are suggested)
- Only **models with web search** are offered (currently Anthropic models)
- Episodes are generated with the just-made persona as context; existing files are skipped unless "既存を作り直す" is on
- Turning web search off relies on model knowledge alone, so quotes are more likely to be invented

### 4.9 AI chat

**AIチャット (AI chat)** in the sidebar lets you talk with any character that has a persona.

- "＋ 新しい会話" starts a chat: pick the project, the character, model, effort, and optionally "about you" (your relationship, etc.)
- The system prompt is a **shared template** with that character's persona and episodes inserted **in full**. Edit it with "共通システム指示を編集"
  - `{{CHARACTER}}` → name, `{{PERSONA_EPISODE}}` → persona + episode YAML, `{{USER}}` (optional) → "about you"
  - Stored at `~/.divergence_z/chat_template.md` (never in the repository)
- The system prompt is long (tens of thousands of tokens), so Anthropic models use prompt caching: later turns pay about a tenth for it
- Chat logs are saved in the project folder under `chats/` and stay on your machine
- Depending on the template, a model's safeguards may decline the request (`ERR::refusal`)

### 4.10 Settings

The **設定 (Settings)** tab sets the project name, manuscript folder, description language, and **the model and effort for each step** — e.g. a large model at `max` for extraction and a cheap model at `low` for trial translations.

## 5. Using the CLI

Everything the app does is also available from the command line. Put a `.env` at the repo root (see `.env.example`) and run from `divergence_z/`.

```bash
cd divergence_z
PY=../.venv/bin/python
```

### With source text

```bash
# 1. Cast sheet → casts/STARGAZER_cast.yaml (review and edit it before continuing)
$PY cast_extractor.py -s ../path/to/STARGAZER/ --work "STARGAZER ≠consciousness"

# 2. Personas → personas/{label}_extracted_v33.yaml
$PY persona_extractor_v2.py -s ../path/to/STARGAZER/ --cast casts/STARGAZER_cast.yaml \
  --characters "宇宙から来た少女,主人公" --lang en

# 3. Episodes → episodes/{label}_Episode.yaml (prints quote verification)
$PY episode_extractor.py -s ../path/to/STARGAZER/ --cast casts/STARGAZER_cast.yaml \
  --characters "宇宙から来た少女,主人公" --work "STARGAZER ≠consciousness" --lang en

# 4. Translation → translations/STARGAZER_en/
$PY chapter_translator.py -s ../path/to/STARGAZER/ --cast casts/STARGAZER_cast.yaml \
  -t en --chapters 0-2          # chapters 0–2; omit for all
$PY chapter_translator.py ... --dry-run   # tokens and cost only, no API calls
```

Long chapters (over 6,000 characters by default, `--max-section-chars`) are first planned by the model into
scene-level sections, then translated one section per call. Each call gets the chapter plan, the translation
just before it, and the bible of only the characters in that section. A stopped run resumes at the next section.

`--cast` can be omitted for works where characters are named. `--source` also accepts a single file (txt / md / pdf / epub).

### Localization

```bash
$PY localizer.py --list-presets
# finished chapters in translations/STARGAZER_en/ with PG15 → translations/en@pg15/
$PY localizer.py -i translations/STARGAZER_en -t en -p pg15
$PY localizer.py ... -p market_adapt -p pg15 --set violence=keep   # stack presets, override a domain
$PY localizer.py ... -p pg15 --revert stargazer_ep01:E003          # revert one edit (no API call)
```

### Without source text (web search)

```bash
$PY persona_generator.py --name "Kurisu Makise" --source "Steins;Gate" --desc "genius neuroscientist" --lang en
$PY episode_generator.py --name "Kurisu Makise" --source "Steins;Gate" --desc "genius neuroscientist" --lang en
```

### Voice

```bash
$PY persona_voice.py --persona "personas/宇宙から来た少女_extracted_v33.yaml" \
  --episode "episodes/宇宙から来た少女_Episode.yaml" \
  --input "Let's have curry tonight" --context "the protagonist's kitchen" --output-lang en

# Two characters
$PY persona_voice.py --persona A.yaml --target-persona B.yaml --dual --input "..." --context "..."
```

### Common options

| Option | Meaning |
|---|---|
| `--model` / `-m` | Model id from the registry (unregistered names also work) |
| `--effort` | `none/low/medium/high/xhigh/max` (supported values depend on the model) |
| `--lang` | Language for descriptions (dialogue and speech patterns stay in the source language) |
| `--help` | All options |

Legacy flags `--thinking N`, `--budget N`, `--reasoning` are still accepted (`--thinking` / `--budget` map to `--effort high`).

## 6. Models and cost

### Model registry

The app and the CLI share one registry. Built-in models:

| Model | Default use | Context | Price (in / out, per 1M tokens) |
|---|---|---|---|
| `gpt-5.6-sol` | cast, persona, episode, translation | not set (depends on your plan) | not set |
| `claude-opus-5-5` | voice, web generation | 1,000,000 | $4 / $20 |
| `claude-sonnet-5-5` | — | 1,000,000 | $2 / $10 |
| `claude-fable-5-1` | — | 1,000,000 | $10 / $50 |
| `claude-opus-4-5-20251101` | previous default | 200,000 | $5 / $25 |
| `claude-haiku-4-5` | — | 200,000 | $1 / $5 |

To add models or fix values, copy `divergence_z/models.example.yaml` to `~/.divergence_z/models.yaml` and edit it.
**For models without a context window (such as `gpt-5.6-sol`), filling it in enables the "does it fit" check in estimates.**

### Typical cost

Estimates count one Japanese character as ~1.4 tokens. For reference (a ~120k-character novel, 26 chapters):

- Cast, persona, and episode steps send the whole text each time (~140k input tokens)
- Translation sends 70–80k input tokens per chapter (source + bible + glossary + previous chapters) — about $0.5 per chapter on Claude Opus 5.5

Always check with **$ 見積もる** (or `--dry-run` in the CLI) first.

## 7. Project folder layout

```
MyProject/
  project.yaml            name, manuscript path, languages, per-step models
  casts/cast.yaml         cast sheet
  personas/               persona YAML
  episodes/               episode YAML
  translations/<lang>/
    <chapter>.<lang>.md             translation
    <chapter>.<lang>.segments.json  source/translation paragraph alignment
    translation_notes.yaml          glossary (safe to edit by hand)
  translations/<lang>@<variant>/    localized version (L0 is never changed)
    <chapter>.<lang>.md / .annotated.md / .ledger.json / .diagnosis.md, policy.yaml
  localize/presets/       project-specific localization presets
  .dz/jobs/               job history (never contains API keys)
```

Everything is plain YAML / Markdown. Edit files directly and the app picks the changes up.

## 8. Privacy and security

- API keys are encrypted with the OS keychain and never reach the app's UI layer
- The engine (Python) listens only on 127.0.0.1 and rejects any request without the per-launch token
- Manuscripts, bibles, and translations are stored only in your project folder. The only data that leaves your machine is what each step sends to OpenAI / Anthropic under your own key
- Use other people's works only within what the rights holder permits

## 9. Troubleshooting

| Symptom | Fix |
|---|---|
| `ENGINE DOWN` at the bottom left | Check `~/Library/Application Support/divergence-z-app/sidecar.log`. If `.venv` or dependencies are missing, redo [3. Install](#3-install). Set `DZ_PYTHON` to use another Python |
| `ERR::auth_missing` | No key for that model's provider — set it in Keys & Models |
| `ERR::auth_invalid` | Invalid key, or no access to that model |
| `ERR::context_too_large` | Text + bible don't fit — choose a model with a larger context |
| `ERR::rate_limited` | Wait and run again (it resumes where it stopped) |
| `ERR::refusal` | The model declined the request — check the content or try another model |
| Chapter shows `INCOMPLETE` | Missing paragraphs were detected — translate it again |
| A `*_BROKEN.yaml` file appeared | The model returned invalid YAML — fix and rename it, or run again |
| Bible files keep an old label | Existing files are skipped — delete them and run again |
| Cast, bible, or translations don't load | Check that the 原稿フォルダ (manuscript folder) isn't a project folder: it only supplies the manuscript. Open a folder with `project.yaml` as a project from the list instead (the app now asks when you pick one) |

## 10. For developers

```
app/                     desktop app (Electron + React)            → app/README.md
divergence_z/
  core/                  LLM layer (BYOK), model registry, loaders, YAML helpers
  server/                local API (FastAPI, jobs, SSE)             → divergence_z/server/README.md
  cast_extractor.py      cast sheet
  persona_extractor_v2.py / persona_generator.py   persona (from text / via web search)
  episode_extractor.py / episode_generator.py      episodes (from text / via web search)
  chapter_translator.py  chapter-level translation
  persona_voice.py       voice
  old/                   legacy Z-axis translation system (archive)
```

Every script is also a library (see `divergence_z/README.md`):

```python
from divergence_z.core import LLM, Keys, load_source_corpus
from divergence_z.persona_extractor_v2 import extract_persona

corpus, _ = load_source_corpus("path/to/STARGAZER/")
result = extract_persona(corpus, "宇宙から来た少女", llm=LLM(Keys(openai="sk-...")),
                         effort="high", output_lang="en")
print(result.valid, result.yaml_text)
```

## 11. Ethics, legacy system, paper, license

- **Ethical restrictions:** a persona reproduces not only how a character speaks but how they perceive the world. Creating personas of deceased real people, among other uses, is prohibited. Read [EthicalRestrictions.md](EthicalRestrictions.md) before use
- **Legacy system:** the earlier pipeline that estimated a Z-axis state per line and scored translations with IAP / ZAP lives in `divergence_z/old/` ([old/README.md](divergence_z/old/README.md)). The experiment results in `Result/` were produced with it
- **Paper:** a practice report on the legacy system has been submitted to the *Journal of Audiovisual Translation (JAT)* — *Translation as Action Preservation (TAP): Evaluating Anime/Manga Translation Beyond Meaning*
- **License:** MIT

```bibtex
@article{tap2026,
  title={Translation as Action Preservation: Evaluating Anime/Manga Translation Beyond Meaning},
  author={[anonymous]},
  journal={Journal of Audiovisual Translation},
  year={2026},
  note={Practice Report}
}
```
