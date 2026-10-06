import type { TablePayload } from "../types";

export function TableView({ table }: { table: TablePayload }) {
  const highlighted = new Set(table.highlight_rows.map((rowNo) => rowNo - 1));
  return (
    <div className="table-card">
      <div className="table-caption">{table.caption}</div>
      <div className="table-scroll">
        <table>
          <tbody>
            {table.rows.map((row, rowIndex) => (
              <tr key={rowIndex} className={highlighted.has(rowIndex) ? "highlight-row" : ""}>
                {row.map((cell, cellIndex) => (
                  <td key={cellIndex}>{cell}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {table.notes.length > 0 && (
        <div className="table-notes">{table.notes.join(" ")}</div>
      )}
    </div>
  );
}
