import React, { useEffect, useRef, useState } from "react";
import { Editor } from "@tiptap/react";

const TABLE_MIN = 2;
const TABLE_MAX = 10;

type Props = {
  editor: Editor | null;
};

const TablePicker: React.FC<Props> = ({ editor }) => {
  const [open, setOpen] = useState(false);
  const [hoverPos, setHoverPos] = useState({ row: TABLE_MIN, col: TABLE_MIN });
  const pickerRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (open && pickerRef.current && !pickerRef.current.contains(event.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [open]);

  useEffect(() => {
    if (open) {
      setHoverPos({ row: TABLE_MIN, col: TABLE_MIN });
    }
  }, [open]);

  const insertTable = (rows: number, cols: number) => {
    if (!editor) {
      return;
    }
    editor.chain().focus().insertTable({ rows, cols, withHeaderRow: true }).run();
    setOpen(false);
  };

  const gridCount = TABLE_MAX - TABLE_MIN + 1;

  return (
    <div className="table-picker" ref={pickerRef}>
      <button onClick={() => setOpen((prev) => !prev)}>Table</button>
      {open && (
        <div className="table-grid">
          <div className="table-grid__cells">
            {Array.from({ length: gridCount }).map((_, rowIndex) =>
              Array.from({ length: gridCount }).map((_, colIndex) => {
                const rows = rowIndex + TABLE_MIN;
                const cols = colIndex + TABLE_MIN;
                const active = rowIndex <= hoverPos.row - TABLE_MIN && colIndex <= hoverPos.col - TABLE_MIN;
                return (
                  <button
                    key={`${rows}x${cols}`}
                    className={active ? "active" : ""}
                    onMouseEnter={() => setHoverPos({ row: rows, col: cols })}
                    onClick={() => insertTable(rows, cols)}
                    aria-label={`Insert ${rows} by ${cols} table`}
                  />
                );
              })
            )}
          </div>
          <span className="table-picker-label">
            Insert {hoverPos.row}×{hoverPos.col}
          </span>
        </div>
      )}
    </div>
  );
};

export default TablePicker;
