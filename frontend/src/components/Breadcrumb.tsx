import { Fragment } from "react";
import { Link } from "react-router-dom";

export interface Crumb {
  label: string;
  to?: string; // none: the page itself (the last one)
}

/** Where a page is in its hierarchy: "Audiobooks › The Series › A Book". */
export function Breadcrumb({ items }: { items: Crumb[] }) {
  return (
    <nav className="breadcrumb" aria-label="Breadcrumb">
      <ol className="breadcrumb__list">
        {items.map((item, i) => (
          <Fragment key={`${i}:${item.label}`}>
            <li className="breadcrumb__item">
              {item.to && i < items.length - 1 ? (
                <Link className="breadcrumb__link" to={item.to}>
                  {item.label}
                </Link>
              ) : (
                <span aria-current="page">{item.label}</span>
              )}
            </li>
            {i < items.length - 1 && (
              <li className="breadcrumb__separator" aria-hidden="true">
                ›
              </li>
            )}
          </Fragment>
        ))}
      </ol>
    </nav>
  );
}
