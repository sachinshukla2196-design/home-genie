import React, { createContext, useContext, useEffect, useState } from "react";

const CartContext = createContext(null);
const KEY = "hg_cart";

const lineKey = (pid, variant) => `${pid}__${variant || ""}`;

export function CartProvider({ children }) {
  const [items, setItems] = useState(() => {
    try { return JSON.parse(localStorage.getItem(KEY) || "[]"); } catch { return []; }
  });

  useEffect(() => { localStorage.setItem(KEY, JSON.stringify(items)); }, [items]);

  const add = (product, qty = 1, variant = "") => {
    setItems((prev) => {
      const k = lineKey(product.id, variant);
      const found = prev.find((i) => lineKey(i.product_id, i.variant) === k);
      if (found) return prev.map((i) => lineKey(i.product_id, i.variant) === k ? { ...i, quantity: i.quantity + qty } : i);
      return [...prev, {
        product_id: product.id, sku: product.sku, name: product.name, name_hi: product.name_hi,
        price: product.selling_price, image: (product.images || [])[0], quantity: qty,
        variant: variant || "",
      }];
    });
  };
  const setQty = (pid, qty, variant = "") => setItems((prev) => prev.map((i) =>
    lineKey(i.product_id, i.variant) === lineKey(pid, variant) ? { ...i, quantity: Math.max(1, qty) } : i));
  const remove = (pid, variant = "") => setItems((prev) => prev.filter((i) =>
    lineKey(i.product_id, i.variant) !== lineKey(pid, variant)));
  const clear = () => setItems([]);

  const count = items.reduce((s, i) => s + i.quantity, 0);
  const subtotal = items.reduce((s, i) => s + i.price * i.quantity, 0);

  return (
    <CartContext.Provider value={{ items, add, setQty, remove, clear, count, subtotal }}>
      {children}
    </CartContext.Provider>
  );
}

export const useCart = () => useContext(CartContext);
