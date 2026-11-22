import { describe, expect, it } from 'vitest';
import { render } from '../../test/render';
import { TableShell } from './Tabs';

/**
 * Regression: TableShell receives a consumer-owned <table>. Wrapping it in a
 * second <table> produced nested tables, which broke horizontal clipping on
 * narrow viewports (results/history/compare pages scrolled the whole document).
 */
describe('TableShell', () => {
  it('renders exactly one table and keeps it inside the scroll region', () => {
    const { container, unmount } = render(
      <TableShell label="Trades">
        <table className="min-w-[560px]">
          <thead>
            <tr>
              <th>date</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>2026-11-13</td>
            </tr>
          </tbody>
        </table>
      </TableShell>,
    );

    expect(container.querySelectorAll('table')).toHaveLength(1);
    const region = container.querySelector('[role="region"]');
    expect(region).not.toBeNull();
    expect(region?.getAttribute('aria-label')).toBe('Trades');
    expect(region?.className).toContain('overflow-x-auto');
    // Chromium leaks a wide table's layout overflow to the document even with
    // overflow-x:auto; paint containment keeps the page itself within 100vw.
    expect(region?.className).toContain('[contain:paint]');
    expect(region?.querySelector('table')).not.toBeNull();
    expect(container.querySelector('table table')).toBeNull();
    unmount();
  });
});
