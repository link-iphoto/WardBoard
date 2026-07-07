# WardBoard

病棟内で使う、ローカル完結型の車椅子・離床管理Webアプリです。

## 起動

現場用はターミナルを表示しない起動ファイルを使います。

```text
WardBoard起動.vbs
```

開発用にログを見ながら起動する場合は次を使います。

```text
start_wardboard_dev.bat
```

起動後、ブラウザで次を開きます。

```text
http://127.0.0.1:58731/timeline
```

終了用:

```text
stop_wardboard.bat
```

起動ポートは `wardboard_config.json` で一箇所管理しています。WardBoard は固定ポート運用のため、58731 が使えない場合でも別ポートへ自動退避しません。

## 現在の範囲

- 患者マスタ
- 車椅子マスタ
- 月〜金の曜日ベースタイムライン
- 30分単位の配置、移動、伸縮
- 同一車椅子・同一患者の時間帯重複チェック
- タイムラインから生成する印刷用離床表

予定は日付ではなく `day_of_week` に `monday` / `tuesday` / `wednesday` / `thursday` / `friday` を保存します。
