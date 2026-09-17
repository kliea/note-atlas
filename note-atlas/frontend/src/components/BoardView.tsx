export function BoardView() {
  return (
    <section className="board-view" aria-label="Board">
      <div className="board-canvas" role="application" aria-label="Empty board canvas">
        <p className="board-placeholder">Empty board. Notes will appear here later.</p>
      </div>
    </section>
  );
}
