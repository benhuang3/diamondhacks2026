// Sole Haven storefront — cart state lives in localStorage.
const CART_KEY = "pixel-peddler-cart";

function loadCart() {
  try {
    const raw = localStorage.getItem(CART_KEY);
    return raw ? JSON.parse(raw) : {};
  } catch (_) {
    return {};
  }
}

function saveCart(cart) {
  localStorage.setItem(CART_KEY, JSON.stringify(cart));
}

function cartItemCount(cart) {
  return Object.values(cart).reduce((sum, qty) => sum + qty, 0);
}

function formatPrice(value) {
  return `$${value.toFixed(2)}`;
}

function updateCartBadge() {
  const el = document.getElementById("cart-count");
  if (!el) return;
  el.textContent = String(cartItemCount(loadCart()));
}

function addToCart(productId) {
  const cart = loadCart();
  cart[productId] = (cart[productId] || 0) + 1;
  saveCart(cart);
  updateCartBadge();
}

function setQuantity(productId, qty) {
  const cart = loadCart();
  if (qty <= 0) {
    delete cart[productId];
  } else {
    cart[productId] = qty;
  }
  saveCart(cart);
  updateCartBadge();
}

function renderProductGrid() {
  const grid = document.getElementById("product-grid");
  if (!grid) return;
  grid.innerHTML = "";
  for (const product of PRODUCTS) {
    const card = document.createElement("article");
    card.className = "product-card";
    card.innerHTML = `
      <div class="product-thumb" aria-hidden="true">${product.icon}</div>
      <h3 class="product-name">${product.name}</h3>
      <p class="product-desc">${product.description}</p>
      <div class="product-footer">
        <span class="product-price">${formatPrice(product.price)}</span>
        <button class="btn btn-primary" data-add="${product.id}">Add to cart</button>
      </div>
    `;
    grid.appendChild(card);
  }
  grid.addEventListener("click", (e) => {
    const target = e.target.closest("[data-add]");
    if (!target) return;
    addToCart(target.getAttribute("data-add"));
    target.textContent = "Added ✓";
    setTimeout(() => { target.textContent = "Add to cart"; }, 900);
  });
}

function renderCart() {
  const container = document.getElementById("cart-container");
  const checkoutSection = document.getElementById("checkout-section");
  if (!container) return;

  const cart = loadCart();
  const entries = Object.entries(cart);

  if (entries.length === 0) {
    container.innerHTML = `
      <div class="empty-state">
        <p>Your cart is empty.</p>
        <a href="index.html" class="btn btn-primary">Browse products</a>
      </div>
    `;
    if (checkoutSection) checkoutSection.hidden = true;
    return;
  }

  let subtotal = 0;
  const rows = entries.map(([id, qty]) => {
    const product = PRODUCTS.find((p) => p.id === id);
    if (!product) return "";
    const lineTotal = product.price * qty;
    subtotal += lineTotal;
    return `
      <tr>
        <td>
          <div class="cart-item">
            <span class="cart-thumb" aria-hidden="true">${product.icon}</span>
            <div>
              <div class="cart-item-name">${product.name}</div>
              <div class="cart-item-desc">${product.description}</div>
            </div>
          </div>
        </td>
        <td class="num">${formatPrice(product.price)}</td>
        <td>
          <div class="qty-control">
            <button class="qty-btn" data-dec="${id}" aria-label="Decrease quantity">−</button>
            <span class="qty-value">${qty}</span>
            <button class="qty-btn" data-inc="${id}" aria-label="Increase quantity">+</button>
          </div>
        </td>
        <td class="num">${formatPrice(lineTotal)}</td>
        <td><button class="link-btn" data-remove="${id}">Remove</button></td>
      </tr>
    `;
  }).join("");

  const tax = subtotal * 0.08;
  const total = subtotal + tax;

  container.innerHTML = `
    <table class="cart-table">
      <thead>
        <tr>
          <th scope="col">Item</th>
          <th scope="col" class="num">Price</th>
          <th scope="col">Qty</th>
          <th scope="col" class="num">Total</th>
          <th scope="col"><span class="sr-only">Actions</span></th>
        </tr>
      </thead>
      <tbody>${rows}</tbody>
    </table>
    <div class="cart-summary">
      <div><span>Subtotal</span><span>${formatPrice(subtotal)}</span></div>
      <div><span>Tax (8%)</span><span>${formatPrice(tax)}</span></div>
      <div class="cart-total"><span>Total</span><span>${formatPrice(total)}</span></div>
    </div>
  `;

  container.addEventListener("click", (e) => {
    const inc = e.target.closest("[data-inc]");
    const dec = e.target.closest("[data-dec]");
    const rem = e.target.closest("[data-remove]");
    if (inc) {
      const id = inc.getAttribute("data-inc");
      setQuantity(id, (loadCart()[id] || 0) + 1);
      renderCart();
    } else if (dec) {
      const id = dec.getAttribute("data-dec");
      setQuantity(id, (loadCart()[id] || 0) - 1);
      renderCart();
    } else if (rem) {
      setQuantity(rem.getAttribute("data-remove"), 0);
      renderCart();
    }
  }, { once: true });

  if (checkoutSection) checkoutSection.hidden = false;
}

function wireCheckoutForm() {
  const form = document.getElementById("checkout-form");
  if (!form) return;
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const msg = document.getElementById("checkout-message");
    if (msg) {
      msg.textContent = "This is a demo store. No order was placed.";
      msg.className = "checkout-message checkout-message-info";
    }
  });
}

document.addEventListener("DOMContentLoaded", () => {
  updateCartBadge();
  renderProductGrid();
  renderCart();
  wireCheckoutForm();
});
