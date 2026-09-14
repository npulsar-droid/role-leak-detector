# role-leak-detector

Claude Code の返答に紛れ込む **偽の `user` ターン**（role-boundary leak）を、
`Stop` フックで自動的に検出する 1 ファイルのスクリプト。依存ゼロ。

**Install:** copy `detect-fake-user.py` to `~/.claude/hooks/` and register it as a `Stop` hook in `~/.claude/settings.json` (see 入れ方 below).
**Output:** `~/.claude/hooks/detections.log`. It logs and beeps; it never alters the session.
**Caveat:** heuristic. A nonexistent-path hit may just be a directory the assistant proposed but has not created yet.

> A `Stop` hook for Claude Code that detects fabricated `user` turns leaking into the
> assistant's own output, plus three related artifact classes. Single file, no dependencies.
> Related: [anthropics/claude-code#44778](https://github.com/anthropics/claude-code/issues/44778)

---

## これは何を見つけるのか

Claude Code は、まれに**自分の返答の末尾に「ユーザーが次に言いそうなこと」を書いてしまう**ことがあります。
画面上はユーザーの発言に見えますが、記録上は `role: assistant` のままです。

```
（アシスタントの本文）
…

user それでいいよ、進めて          ← 誰も打っていない
```

実測では **3,790 メッセージ中 23 件（0.61%）**。多くは無害な相槌ですが、
**承認・指示・出典の付与**として現れることがあります。

## 検出する 4 + 1 軸

| | 内容 |
|---|---|
| ラベル漏れ | `user` / `système` が行頭に現れる（`user1000円` `user一応、` のように区切りが無い形も拾う） |
| 文字体系の混入 | キリル・ギリシャ・ハングル・タイ他 8 種、および日本語で使わない簡体字。`формальな書類` のように**意味は正しく言語だけ違う**現象 |
| 存在しないパス | 出力に現れたローカルパスの実在確認（**外部通信なし**） |
| URL の記録 | 出力に現れた URL を `refs.log` に追記するだけ（判定しない） |
| 返答の未完了 | 直前の assistant メッセージに `stop_reason` が無い＝生成が途中で切れた記録。**推測を含まない唯一の軸**（CLI では無効。下記参照） |

## 検出できないもの（重要）

- **ラベルの無い捏造**。実際に存在します（ラベル漏れの直後に、無印で続いた例が 1 件）。
  数を見積もる手段はありません。
- **画面には出たがログに残らないもの**。逆に、画面のラベル表示が本文として保存された例もあり、
  UI とトランスクリプトは**どちらの方向にも一致しません**。
- **本物のユーザー発言が assistant 側に取り込まれた場合**との区別。
  どちらも「assistant 本文の行頭 `user`」として現れます。
- **入力欄の候補を採用したもの**。それは正規の `role: user` として記録されるため、痕跡が残りません。
- **CLI での「返答の未完了」**。CLI（`entrypoint: cli`）は正常な応答でも `stop_reason` を
  書かないことがあるため、この軸だけ自動的に無効化します。デスクトップアプリでは
  3,900 件中 1 件しか欠けませんでしたが、CLI では通常の応答でも欠けました。
  他の 4 軸は CLI でもそのまま動きます。

## 入れ方

```bash
mkdir -p ~/.claude/hooks
curl -o ~/.claude/hooks/detect-fake-user.py \
  https://raw.githubusercontent.com/npulsar-droid/role-leak-detector/main/detect-fake-user.py
```

`~/.claude/settings.json` に追加:

```json
{
  "hooks": {
    "Stop": [
      { "hooks": [ { "type": "command", "command": "python3 ~/.claude/hooks/detect-fake-user.py" } ] }
    ]
  }
}
```

**終了コードは常に 0** です。停止をブロックしません（`exit 2` はループの危険があるため使いません）。

## 出力

```
~/.claude/hooks/detections.log     検出の記録（消えない）
~/.claude/hooks/refs.log           出力に現れた URL
~/.claude/hooks/invocations.log    呼び出しの記録（不要なら該当行を消してよい）
```

検出時は **macOS ならシステム音**、それ以外は端末ベルが鳴ります。
`CLAUDE_DETECT_SOUND=0` で無効化。

画面表示は環境によります（`systemMessage` はデスクトップアプリで表示された実績あり）。
**表示されなくても `detections.log` には必ず残ります。**

## 過去ログを一括で調べる

```bash
python3 ~/.claude/hooks/detect-fake-user.py --test ~/.claude/projects/<project>/<session>.jsonl
```

## 発生条件を自分のログで数える

`leak_context_stats.py` は `~/.claude/projects/**/*.jsonl` を全部読んで、
assistant メッセージ1件ごとに特徴量を出し、**どの条件で漏れやすいか**を表にします。

```bash
python3 leak_context_stats.py
```

文脈長・エージェント的ターンの深さ・直前のレコード種別・人間の発言からの経過秒数・
セッション内の先行漏れ数・compact からの距離・モデル・日付などで、それぞれ検出率を出します。
同時に `feat.csv`（1行＝1 assistant メッセージ）を作業ディレクトリに書きます。

**`feat.csv` は自分のログの断片を含みます。** 各行に assistant 本文の冒頭 80 文字が入るので、
そのまま共有しないでください（このリポジトリでは `.gitignore` 済み）。共有するなら
`head` 列を落としてから。集計の表そのものには本文は入りません。

[#44778 の追加報告](https://github.com/anthropics/claude-code/issues/44778)の数字は、
このスクリプトを筆者のログに掛けた結果です。**1人分のデータでは条件の切り分けができない**ので、
走らせた結果を issue に貼ってもらえると助かります。

## 自分の記憶にない発言を確認する

```bash
grep -h "<覚えのない文字列>" ~/.claude/projects/**/*.jsonl \
  | python3 -c "import json,sys; [print(json.loads(l)['message']['role']) for l in sys.stdin]" \
  | sort | uniq -c
```

`assistant` しか出てこなければ、それは捏造です。`role: user` のレコードが存在しません。

## 誤検知しやすいもの

検出器は捏造そのものではなく、捏造に伴いやすい**痕跡**を見ています。
鳴ったからといって捏造とは限りません。判断は `detections.log` を読んで人間がします。

- **存在しないパス**は、まだ作っていないディレクトリの提案（`~/.agent-log-backup/` を作りましょう）、
  例示用のパス（`~/Desktop/xxx.png`）、省略して書いたパス（`.../hooks/detect-fake-user.py`）にも反応します。
  実運用で出た誤検知の大半はこの軸です。
- **文字体系の混入**は、引用や翻訳で外国語をそのまま書いた場合にも反応します。
- **返答の未完了**は CLI では自動的に無効ですが、デスクトップアプリでも Esc で止めた返答には反応します。

検出時にセッションを止めたり本文を書き換えたりはしません。ログに書いて音を鳴らすだけです。

## 注意

検出器の穴は、これまで **5 回とも実際の発生によって見つかりました**（机上のテストでは出ませんでした）。
おそらくまだ穴があります。見つけたら issue でも PR でも歓迎します。



## License

MIT
