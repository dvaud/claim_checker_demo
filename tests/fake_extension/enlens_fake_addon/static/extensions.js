// The stand-in add-on's page module (0.13.6), served as /static/addons/fake/extensions.js. It adds a part of the app
// ("Notes"), a page with a sidebar entry and an Overview card, the name of its job, a welcome card and the result
// page's link back to the note a hypothesis comes from.
function renderNotes(view) {
  const h1 = document.createElement("h1");
  h1.id = "page-title";
  h1.textContent = "Notes";
  view.appendChild(h1);
}

export default () => ({
  sections: { notes: { title: "Your notes", short: "Notes", sub: "What you wrote down in the field." } },
  features: {
    notes: {
      section: "notes", title: "Notes", icon: "file-pen", href: "#/fake/notes", ai: "optional", nav: true,
      what: "Your own notes from the field, tagged by the AI.",
      state: (o) => (o.fake_notes ? [true, `${o.fake_notes} notes`] : [false, "None yet"]),
    },
    // never replaces one of ENLENS's
    check: { section: "notes", title: "Not ENLENS's check" },
  },
  routes: [[/^\/fake\/notes$/, "notes", renderNotes]],
  jobKinds: { "fake-labels": { icon: "tag", text: "Stand-in labels", link: "#/fake/notes", withJob: true } },
  welcome: [{ icon: "file-pen", title: "Bring your field notes", text: "They are tagged and checked like documents." }],
  origins: { "fake-note": { eyebrow: "Back to the note", meta: "from a note", href: (id) => `#/fake/notes?note=${encodeURIComponent(id)}` } },
});
