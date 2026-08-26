# Kindle ハイライトの吸い出し手順

`read.amazon.co.jp/notebook`（Kindle の「メモとハイライト」）から、線を引いた箇所を
まとめて `kindle-archive/highlights.json` に落とすための手順。**オーナーの手作業が要る。**

LINE と同じ「API が無いので手動エクスポート一択」型のソース。所要 5〜10 分。

---

## なぜこの方法しかないのか

| 経路 | 可否 | 理由 |
|---|---|---|
| 公式のエクスポート API | ✗ | 存在しない |
| Kindle for Mac のローカル DB | ✗ | `~/Library/Containers/com.amazon.Lassen/Data/Library/AnnotationStorage` を実際に開いて確認した。全 32 行のうち `highlight` は **1 件**だけで、残りは読書位置レコード。**ハイライト本文のカラムが空**で使い物にならない（2026-08-26 実測） |
| Kindle 実機の `My Clippings.txt` | △ | 実機で読んだ本しか入らない。この Mac には存在しなかった。実機中心の本があるなら補助的に使える |
| `read.amazon.co.jp/notebook` をブラウザで読む | **○** | ログイン済みのブラウザなら全書籍のハイライトが見られる。**これが本命** |

Amazon にログインした状態のブラウザでしか読めないので、Python スクリプトからは取れない。
だから「オーナーが DevTools でスニペットを1回貼る」という形にしている。

---

## 手順

### 1. notebook を開く

ブラウザ（Chrome / Edge 推奨）で <https://read.amazon.co.jp/notebook> を開く。
左側に本棚が並び、本をクリックすると右にハイライトが出る画面。

出ない場合は Amazon にログインし直す。

### 2. DevTools のコンソールを開く

`Option + Command + I`（Mac）→ 上部のタブで **Console** を選ぶ。

初回は「危険なので貼るな」という警告が出ることがある。その場合はコンソールに
`許可` / `allow pasting` と打ってから Enter を押すと貼れるようになる。

### 3. 下のスニペットを全部コピーして貼り、Enter

進捗が `[3/43] 本のタイトル … 12 件（メモ 2）` のように流れる。**全部終わるまで画面を閉じない。**
本の数 × 約 1 秒かかる（Amazon に負荷をかけないよう1冊ずつ間を空けている）。

```js
(async () => {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const txt = (el) => (el ? el.textContent.replace(/\s+/g, " ").trim() : "");

  // --- 1. 左の本棚から書籍一覧を拾う ---
  let cards = [...document.querySelectorAll(".kp-notebook-library-each-book")];
  if (!cards.length) cards = [...document.querySelectorAll('[id^="B0"]')];
  if (!cards.length) {
    console.error("本棚が読めませんでした。read.amazon.co.jp/notebook を開いた状態で実行してください。");
    return;
  }
  const shelf = cards.map((c) => ({
    asin: c.id || txt(c.querySelector("[data-asin]")),
    title: txt(c.querySelector("h2")) || txt(c.querySelector(".kp-notebook-searchable")),
    author: txt(c.querySelector("p")).replace(/^(著者|作成者)[:：]\s*/, ""),
  })).filter((b) => b.asin);
  console.log(`本棚: ${shelf.length} 冊`);

  // --- 2. 1冊ずつハイライトを取る ---
  const parsePage = (doc) => {
    const out = [];
    for (const h of doc.querySelectorAll('[id="highlight"], .kp-notebook-highlight')) {
      const text = txt(h);
      if (!text) continue;
      // ハイライト本文と同じ塊にあるヘッダー（色・位置）とメモを、上へ最大6階層たどって探す。
      // 途中でハイライトを2つ以上含む階層に出たら行き過ぎなので打ち切る（隣の注釈と混ざるため）。
      let box = null, header = null, note = null, cur = h;
      for (let d = 0; d < 6 && cur.parentElement; d++) {
        cur = cur.parentElement;
        if (cur.querySelectorAll('[id="highlight"], .kp-notebook-highlight').length > 1) break;
        const hd = cur.querySelector('[id="annotationHighlightHeader"], .kp-notebook-metadata');
        const nt = cur.querySelector('[id="note"]');
        if (hd || nt) { box = cur; header = hd; note = nt; break; }
      }
      const head = txt(header);
      const m = head.match(/位置[:：]?\s*([\d,]+)/);
      const p = head.match(/ページ[:：]?\s*([\d,]+)/);
      const locEl = box && box.querySelector('[id="kp-annotation-location"]');
      out.push({
        text,
        note: txt(note),
        location: m ? m[1].replace(/,/g, "") : (locEl ? (locEl.value || txt(locEl)) : ""),
        page: p ? p[1].replace(/,/g, "") : "",
        color: (head.split("|")[0] || "").replace(/のハイライト/, "").trim(),
      });
    }
    return out;
  };

  const books = [], failed = [];
  for (let i = 0; i < shelf.length; i++) {
    const b = shelf[i];
    try {
      const highlights = [];
      let token = "", limit = "", guard = 0;
      do {
        const url = `/notebook?asin=${b.asin}&contentLimitState=${encodeURIComponent(limit)}&token=${encodeURIComponent(token)}`;
        const res = await fetch(url, { credentials: "include" });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const doc = new DOMParser().parseFromString(await res.text(), "text/html");
        highlights.push(...parsePage(doc));
        token = doc.querySelector(".kp-notebook-annotations-next-page-start")?.value || "";
        limit = doc.querySelector(".kp-notebook-content-limit-state")?.value || "";
      } while (token && ++guard < 50);
      books.push({ ...b, highlights });
      const nn = highlights.filter((x) => x.note).length;
      console.log(`[${i + 1}/${shelf.length}] ${b.title} … ${highlights.length} 件` + (nn ? `（メモ ${nn}）` : ""));
    } catch (e) {
      failed.push({ ...b, reason: String(e && e.message || e) });
      console.warn(`[${i + 1}/${shelf.length}] ${b.title} … 失敗: ${e}`);
    }
    await sleep(700); // Amazon 側に負荷をかけない
  }

  // --- 3. JSON をダウンロード ---
  const withH = books.filter((b) => b.highlights.length);
  const total = withH.reduce((s, b) => s + b.highlights.length, 0);
  const payload = { exported_at: new Date().toISOString(), books, failed };
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" }));
  a.download = "highlights.json";
  a.click();
  console.log(`完了: ${withH.length} 冊 / ハイライト ${total} 件 / 失敗 ${failed.length} 冊`);
})();
```

### 4. 落ちてきた `highlights.json` を置く

ダウンロードフォルダに `highlights.json` が落ちる。これをリポジトリに移す。

```bash
mkdir -p kindle-archive && mv ~/Downloads/highlights.json kindle-archive/
```

### 5. 最後にコンソールに出た「完了: N 冊 / ハイライト M 件」を Claude に伝える

スクリプト側で数え直して突き合わせるため。ここがズレていたら取りこぼしている。

---

## 取り込み（ここからは Claude / スクリプトの仕事）

```bash
python3 scripts/kindle_map.py                 # 地図 → kindle-archive/book_map.tsv
python3 scripts/kindle_extract.py --dry-run   # 何冊書くか確認
python3 scripts/kindle_extract.py             # 本文 → kindle-archive/books/*.md
python3 scripts/kindle_match.py               # books スキルの56冊と書名で突き合わせ
```

---

## うまくいかないとき

| 症状 | 対処 |
|---|---|
| `本棚が読めませんでした` | notebook のページを開いた状態か確認する。それでも出るなら **Amazon 側の HTML が変わっている**ので、コンソールの出力をそのまま Claude に貼ってほしい。セレクタを直す |
| 全部 `… 0 件` になる | 同上。ハイライト部分の HTML が変わっている。1冊クリックした状態で `document.querySelectorAll('[id="highlight"]').length` を打って結果を伝えてほしい |
| ハイライト本文は取れるが**メモ・位置・色が全部空** | ヘッダー部分の HTML が想定と違う。`document.querySelectorAll('[id="annotationHighlightHeader"]').length` と `document.querySelectorAll('[id="note"]').length` を1冊開いた状態で打って、結果を Claude に伝えてほしい |
| 一部の本だけ `失敗` | `failed` に理由付きで残るので、取りこぼしは黙って消えない。件数が少なければその本だけ手で開いてコピーでもよい |
| 途中で止まる | 再実行すれば最初からやり直す。重複はしない（毎回まるごと作り直す） |

> **実測メモ（2026-08-26）** — 実際に走らせて **本棚 43 冊 / ハイライト 766 件 / 失敗 0 冊** を取得できた。
> ただし初回版はハイライト本文しか取れず、**メモ・位置・色が全部空**だった（ヘッダー要素の親を取り違えていた）。
> 上のスニペットはそこを直した版で、**メタデータが取れるかは次回の実行で確認する**。
> 進捗表示に `（メモ 3）` が出れば取れている。

## 更新のしかた

差分取得はできない（notebook は「いつ引いたか」を出さない）ので、**毎回まるごと取り直す**。
本を読んだら適当なタイミングで手順1〜4をもう一度やる。上書きで問題ない。

## 扱いの注意

- `kindle-archive/` は `.gitignore` 済み。**このリポジトリは公開されている**ので、
  書籍本文の逐語がここから外に出ないようにしている。
- `books` スキルの `volumes/*.md`（Git 管理下）には**ハイライト本文を書かない**。
  「ハイライトが N 件ある」というポインタだけを書き、本文はここから読む。
- Podcast / note / ツイートで使うときは引用の範囲（主従関係・出典明記）に注意する。
