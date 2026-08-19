export default function DemoVideo() {
  const source = import.meta.env.VITE_DEMO_VIDEO_SRC;
  const poster = import.meta.env.VITE_DEMO_VIDEO_POSTER;
  if (!source) return null;

  return (
    <section className="dm-container dm-demo-video" aria-labelledby="demo-video-title">
      <div>
        <p className="dm-demo-video-label">Portfolio walkthrough</p>
        <h2 id="demo-video-title">See the evidence flow in motion.</h2>
      </div>
      <video controls preload="none" poster={poster || undefined}>
        <source src={source} />
      </video>
    </section>
  );
}
