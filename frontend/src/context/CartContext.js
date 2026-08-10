import React, { createContext, useContext, useEffect, useState } from "react";

const CartContext = createContext(null);

export function CartProvider({ children }) {
  const [items, setItems] = useState(() => {
    try { return JSON.parse(localStorage.getItem("anj_cart") || "[]"); } catch { return []; }
  });

  useEffect(() => { localStorage.setItem("anj_cart", JSON.stringify(items)); }, [items]);

  const add = (product, qty = 1) => {
    setItems((prev) => {
      const found = prev.find((i) => i.product_id === product.id);
      if (found) return prev.map((i) => i.product_id === product.id ? { ...i, quantity: i.quantity + qty } : i);
      return [...prev, {
        product_id: product.id, sku: product.sku, name: product.name, name_hi: product.name_hi,
        price: product.selling_price, image: (product.images || [])[0], quantity: qty,
      }];
    });
  };
  const setQty = (pid, qty) => setItems((prev) => prev.map((i) => i.product_id === pid ? { ...i, quantity: Math.max(1, qty) } : i));
  const remove = (pid) => setItems((prev) => prev.filter((i) => i.product_id !== pid));
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
