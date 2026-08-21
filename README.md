# role-leak-detector

Claude Code の返答に紛れ込む **偽の `user` ターン**（role-boundary leak）を、
`Stop` フックで自動的に検出する 1 ファイルのスクリプト。依存ゼロ。

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
| 返答の未完了 | 直前の assistant メッセージに `stop_reason` が無い＝生成が途中で切れた記録。**推測を含まない唯一の軸** |

## 検出できないもの（重要）

- **ラベルの無い捏造**。実際に存在します（ラベル漏れの直後に、無印で続いた例が 1 件）。
  数を見積もる手段はありません。
- **画面には出たがログに残らないもの**。逆に、画面のラベル表示が本文として保存された例もあり、
  UI とトランスクリプトは**どちらの方向にも一致しません**。
- **本物のユーザー発言が assistant 側に取り込まれた場合**との区別。
  どちらも「assistant 本文の行頭 `user`」として現れます。
- **入力欄の候補を採用したもの**。それは正規の `role: user` として記録されるため、痕跡が残りません。

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

## 自分の記憶にない発言を確認する

```bash
grep -h "<覚えのない文字列>" ~/.claude/projects/**/*.jsonl \
  | python3 -c "import json,sys; [print(json.loads(l)['message']['role']) for l in sys.stdin]" \
  | sort | uniq -c
```

`assistant` しか出てこなければ、それは捏造です。`role: user` のレコードが存在しません。

## 注意

検出器の穴は、これまで **5 回とも実際の発生によって見つかりました**（机上のテストでは出ませんでした）。
おそらくまだ穴があります。見つけたら issue でも PR でも歓迎します。

## License

MIT
